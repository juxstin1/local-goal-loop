from __future__ import annotations

from typing import Any

import httpx
import pytest
from conftest import initial_state, role_model_for_task
from langchain_core.messages import AIMessage
from langgraph.types import Command
from openai import InternalServerError

from graph_engineer.graph import build_goal_graph
from graph_engineer.model import LocalChatRoleModel
from graph_engineer.packets import GoalContract, PatchDraft, PlanDraft


def approval(result: dict[str, Any]) -> Command:
    value = result["__interrupt__"][0].value
    return Command(
        resume={
            "decision": "approve",
            "feedback": "fixture regression",
            "packet_hash": value["packet_hash"],
            "repository_fingerprint": value["repository_fingerprint"],
        }
    )


def test_model_cannot_redefine_the_goal(fixture_repo, fixture_task):
    model = role_model_for_task(fixture_task)

    def invent_requirements(_):
        raise AssertionError("Model must not define acceptance requirements")

    model.handlers["goal"] = invent_requirements
    graph = build_goal_graph(model)
    config = {"configurable": {"thread_id": "fixed-contract"}}
    graph.invoke(initial_state(fixture_repo, fixture_task), config)
    plan_input = model.calls[0][1]
    assert model.calls[0][0] == "plan"
    assert plan_input["goal"]["objective"] == fixture_task["objective"]
    assert len(plan_input["goal"]["requirements"]) == 1
    assert plan_input["goal"]["requirements"][0]["evidence_required"] == "test:pytest:exit=0"
    assert plan_input["allowed_write_paths"] == ["solution.py"]
    assert any(e["path"] == "test_solution.py" for e in plan_input["context"]["evidence"])
    assert "expected_source" not in str(plan_input)


def test_repair_contains_rejected_fields_and_legal_choices(fixture_repo, fixture_task):
    model = role_model_for_task(fixture_task)
    original = model.handlers["plan"]
    calls = 0

    def plan(payload):
        nonlocal calls
        calls += 1
        value = original(payload)
        if calls == 1:
            value["steps"][0]["evidence_ids"] = ["invented-evidence"]
            value["files"] = ["test_solution.py"]
        else:
            assert payload["invalid_evidence_ids"] == ["invented-evidence"]
            assert payload["invalid_files"] == ["test_solution.py"]
            assert payload["rejected_draft"]["files"] == ["test_solution.py"]
            assert "EVID-001" in payload["allowed_evidence_ids"]
        return value

    model.handlers["plan"] = plan
    graph = build_goal_graph(model)
    graph.invoke(
        initial_state(fixture_repo, fixture_task), {"configurable": {"thread_id": "repair-values"}}
    )
    assert calls == 2


def test_patch_cannot_write_an_unapproved_file_even_if_globally_writable(
    fixture_repo, fixture_task
):
    other = fixture_repo / "other.py"
    other.write_text("original = True\n", encoding="utf-8")
    model = role_model_for_task(fixture_task)
    original_patch = model.handlers["patch"]

    def expand_patch(payload):
        value = original_patch(payload)
        evidence = next(e for e in payload["context"]["evidence"] if e["path"] == "other.py")
        value["replacements"][0].update(
            path="other.py", expected_sha256=evidence["sha256"], content="original = False\n"
        )
        return value

    model.handlers["patch"] = expand_patch
    state = initial_state(fixture_repo, fixture_task)
    state["allowed_write_paths"].append("other.py")
    graph = build_goal_graph(model)
    config = {"configurable": {"thread_id": "approved-files-only"}}
    gate = graph.invoke(state, config)
    assert gate["__interrupt__"][0].value["plan"]["files"] == ["solution.py"]
    with pytest.raises(ValueError, match="not writable"):
        graph.invoke(approval(gate), config)
    assert other.read_text(encoding="utf-8") == "original = True\n"


def test_real_file_evidence_cannot_replace_required_test_receipt(fixture_repo, fixture_task):
    model = role_model_for_task(fixture_task)
    review = model.handlers["review"]

    def overclaim(payload):
        value = review(payload)
        value["requirement_results"][0]["evidence"] = [
            next(e for e in payload["available_evidence"] if e.startswith("file:solution.py:"))
        ]
        return value

    model.handlers["review"] = overclaim
    graph = build_goal_graph(model)
    config = {"configurable": {"thread_id": "unsupported-proof"}}
    current = initial_state(fixture_repo, fixture_task)
    for _ in range(4):
        current = approval(graph.invoke(current, config))
    result = graph.invoke(current, config)
    assert result["tests"][0]["exit_code"] == 0
    assert result["status"] == "revision_cap_reached"
    assert not result["review"]["payload"]["every_requirement_proved"]


def test_test_file_tampering_invalidates_even_a_zero_exit_run(fixture_repo, fixture_task):
    model = role_model_for_task(fixture_task)
    patch = model.handlers["patch"]

    def tamper(payload):
        value = patch(payload)
        value["replacements"][0]["content"] = (
            "from pathlib import Path\n"
            "Path('test_solution.py').write_text('def test_weakened(): pass\\n')\n"
            + fixture_task["expected_source"]
        )
        return value

    model.handlers["patch"] = tamper
    graph = build_goal_graph(model)
    config = {"configurable": {"thread_id": "tampered-tests"}}
    plan = graph.invoke(initial_state(fixture_repo, fixture_task), config)
    patch_gate = graph.invoke(approval(plan), config)
    with pytest.raises(ValueError, match="protected files changed"):
        graph.invoke(approval(patch_gate), config)


class FakeChat:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []
        self.tools = None

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.messages.append(list(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def server_error(message="Failed to parse tool call arguments as JSON"):
    return InternalServerError(
        message,
        response=httpx.Response(
            500, request=httpx.Request("POST", "http://127.0.0.1:8089/v1/chat/completions")
        ),
        body={"error": message},
    )


def goal_message():
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "GoalContract",
                "id": "goal",
                "type": "tool_call",
                "args": {
                    "objective": "Run the fixed test.",
                    "requirements": [
                        {
                            "id": "REQ-001",
                            "statement": "The registered test passes.",
                            "evidence_required": "test:pytest:exit=0",
                        }
                    ],
                    "completion_test": "The registered test exits zero.",
                },
            }
        ],
    )


def test_malformed_json_reenters_bounded_repair(tmp_path):
    fake = FakeChat([server_error(), goal_message()])
    trace = tmp_path / "trace.jsonl"
    model = LocalChatRoleModel(fake, packet_attempts=3, trace_path=trace)
    model.invoke("goal", GoalContract, {"objective": "Run the fixed test."})
    assert len(fake.messages) == 2
    assert "malformed or truncated JSON" in fake.messages[1][-1].content
    assert model.malformed_response_count == 1
    assert len(trace.read_text().splitlines()) == 2


def test_malformed_json_repair_stops_at_attempt_limit():
    fake = FakeChat([server_error(), server_error(), server_error()])
    model = LocalChatRoleModel(fake, packet_attempts=3)
    with pytest.raises(InternalServerError):
        model.invoke("goal", GoalContract, {"objective": "Run the fixed test."})
    assert len(fake.messages) == 3


@pytest.mark.parametrize("error", [server_error("out of memory"), RuntimeError("connection lost")])
def test_unrelated_server_failures_are_not_reprompted(error):
    fake = FakeChat([error])
    with pytest.raises(type(error)):
        LocalChatRoleModel(fake).invoke("goal", GoalContract, {"objective": "Run tests."})
    assert len(fake.messages) == 1


def test_hash_is_filled_by_host_and_tool_paths_are_restricted():
    args = {
        "summary": "Fix addition correctly.",
        "replacements": [
            {
                "path": "solution.py",
                "content": "def add(a, b): return a + b\n",
                "expected_sha256": "model-invented-hash",
            }
        ],
        "test_ids": ["pytest"],
        "rationale": "Use addition.",
    }
    fake = FakeChat(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "_WirePatchDraft", "id": "patch", "type": "tool_call", "args": args}
                ],
            )
        ]
    )
    payload = {
        "approved_plan": {"files": ["solution.py"], "test_ids": ["pytest"]},
        "context": {"evidence": [{"path": "solution.py", "sha256": "a" * 64}]},
    }
    result = LocalChatRoleModel(fake).invoke("patch", PatchDraft, payload)
    assert result.replacements[0].expected_sha256 == "a" * 64
    fields = fake.tools[0]["function"]["parameters"]["$defs"]["_WireFileReplacement"]["properties"]
    assert "expected_sha256" not in fields
    assert fields["path"]["enum"] == ["solution.py"]


def test_plan_schema_limits_evidence_and_write_paths():
    fake = FakeChat([RuntimeError("stop after schema capture")])
    payload = {
        "allowed_write_paths": ["solution.py"],
        "registered_test_ids": ["pytest"],
        "context": {"evidence": [{"id": "EVID-001"}]},
    }
    with pytest.raises(RuntimeError):
        LocalChatRoleModel(fake).invoke("plan", PlanDraft, payload)
    schema = fake.tools[0]["function"]["parameters"]
    assert schema["properties"]["files"]["items"]["enum"] == ["solution.py"]
    assert schema["$defs"]["PlanStep"]["properties"]["evidence_ids"]["items"]["enum"] == [
        "EVID-001"
    ]
