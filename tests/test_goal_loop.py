from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import initial_state, role_model_for_task
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph_engineer.graph import build_goal_graph


def interrupt_value(result: dict[str, Any]) -> dict[str, Any]:
    return result["__interrupt__"][0].value


def approve(value: dict[str, Any]) -> Command:
    return Command(
        resume={
            "decision": "approve",
            "packet_hash": value["packet_hash"],
            "repository_fingerprint": value["repository_fingerprint"],
            "feedback": "approved by test",
        }
    )


def reject(value: dict[str, Any]) -> Command:
    return Command(
        resume={
            "decision": "reject",
            "packet_hash": value["packet_hash"],
            "repository_fingerprint": value["repository_fingerprint"],
            "feedback": "rejected by test",
        }
    )


def invoke_to_next_gate(graph: Any, current: Any, config: dict[str, Any]) -> dict[str, Any]:
    return graph.invoke(current, config)


def test_goal_loop_completes_only_after_both_approvals_and_tests(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    model = role_model_for_task(fixture_task)
    graph = build_goal_graph(model, checkpointer=InMemorySaver(), context_chars=4000)
    config = {"configurable": {"thread_id": "complete-loop"}}

    plan_gate = invoke_to_next_gate(graph, initial_state(fixture_repo, fixture_task), config)
    assert interrupt_value(plan_gate)["gate"] == "plan"

    patch_gate = invoke_to_next_gate(graph, approve(interrupt_value(plan_gate)), config)
    assert interrupt_value(patch_gate)["gate"] == "patch"

    completed = invoke_to_next_gate(graph, approve(interrupt_value(patch_gate)), config)

    assert completed["status"] == "complete"
    assert completed["final_receipt"]["status"] == "complete"
    assert completed["tests"][0]["exit_code"] == 0
    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == fixture_task[
        "expected_source"
    ]
    assert [call[0] for call in model.calls] == ["plan", "patch", "review"]


def test_failed_test_routes_through_a_new_context_plan_and_patch(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    model = role_model_for_task(fixture_task, first_patch_fails=True)
    graph = build_goal_graph(model, checkpointer=InMemorySaver(), context_chars=4000)
    config = {"configurable": {"thread_id": "revision-loop"}}
    current: Any = initial_state(fixture_repo, fixture_task)

    for expected_gate in ("plan", "patch", "plan", "patch"):
        result = graph.invoke(current, config)
        value = interrupt_value(result)
        assert value["gate"] == expected_gate
        current = approve(value)

    completed = graph.invoke(current, config)

    assert completed["status"] == "complete"
    assert completed["iteration"] == 1
    assert [call[0] for call in model.calls] == [
        "plan",
        "patch",
        "review",
        "plan",
        "patch",
        "review",
    ]
    assert [event["stage"] for event in completed["events"]].count("continue") == 1


def test_one_revision_is_the_absolute_maximum(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    model = role_model_for_task(fixture_task, first_patch_fails=True)
    valid_patch = model.handlers["patch"]

    def always_failing_patch(payload: dict[str, Any]) -> dict[str, Any]:
        draft = valid_patch(payload)
        draft["replacements"][0]["content"] = fixture_task["source"]
        return draft

    model.handlers["patch"] = always_failing_patch
    graph = build_goal_graph(model, checkpointer=InMemorySaver(), context_chars=4000)
    config = {"configurable": {"thread_id": "absolute-revision-cap"}}
    current: Any = initial_state(fixture_repo, fixture_task, cycle_budget=99)

    for expected_gate in ("plan", "patch", "plan", "patch"):
        result = graph.invoke(current, config)
        value = interrupt_value(result)
        assert value["gate"] == expected_gate
        current = approve(value)

    capped = graph.invoke(current, config)

    assert capped["status"] == "revision_cap_reached"
    assert capped["final_receipt"]["iterations_completed"] == 2
    assert [event["stage"] for event in capped["events"]].count("continue") == 1
    assert [event["stage"] for event in capped["events"]].count("apply") == 2
    assert "__interrupt__" not in capped


def test_rejected_patch_never_mutates_repository(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    original = (fixture_repo / "solution.py").read_text(encoding="utf-8")
    graph = build_goal_graph(
        role_model_for_task(fixture_task), checkpointer=InMemorySaver(), context_chars=4000
    )
    config = {"configurable": {"thread_id": "reject-patch"}}

    plan_gate = graph.invoke(initial_state(fixture_repo, fixture_task), config)
    patch_gate = graph.invoke(approve(interrupt_value(plan_gate)), config)
    rejected = graph.invoke(reject(interrupt_value(patch_gate)), config)

    assert rejected["status"] == "rejected"
    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == original
    assert rejected.get("tests", []) == []


def test_wrong_approval_hash_is_rejected_before_mutation(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    original = (fixture_repo / "solution.py").read_text(encoding="utf-8")
    graph = build_goal_graph(
        role_model_for_task(fixture_task), checkpointer=InMemorySaver(), context_chars=4000
    )
    config = {"configurable": {"thread_id": "wrong-hash"}}
    plan_gate = graph.invoke(initial_state(fixture_repo, fixture_task), config)
    value = interrupt_value(plan_gate)

    with pytest.raises(ValueError, match="packet hash"):
        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "packet_hash": "0" * 64,
                    "repository_fingerprint": value["repository_fingerprint"],
                    "feedback": "wrong hash",
                }
            ),
            config,
        )

    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == original


def test_invalid_plan_is_repaired_before_the_approval_gate(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    model = role_model_for_task(fixture_task)
    valid_plan = model.handlers["plan"]
    plan_calls = 0

    def repairable_plan(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal plan_calls
        plan_calls += 1
        if plan_calls == 1:
            draft = valid_plan(payload)
            draft["files"] = ["outside-allowlist.py"]
            return draft
        assert payload["validation_feedback"] == (
            "plan requests a file outside the write allowlist"
        )
        return valid_plan(payload)

    model.handlers["plan"] = repairable_plan
    graph = build_goal_graph(model, checkpointer=InMemorySaver(), context_chars=4000)

    result = graph.invoke(
        initial_state(fixture_repo, fixture_task),
        {"configurable": {"thread_id": "repair-plan"}},
    )

    assert interrupt_value(result)["gate"] == "plan"
    assert plan_calls == 2
    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == fixture_task["source"]


def test_invalid_patch_is_repaired_before_the_approval_gate(
    fixture_repo: Path, fixture_task: dict[str, Any]
) -> None:
    model = role_model_for_task(fixture_task)
    valid_patch = model.handlers["patch"]
    patch_calls = 0

    def repairable_patch(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal patch_calls
        patch_calls += 1
        if patch_calls == 1:
            draft = valid_patch(payload)
            draft["replacements"][0]["path"] = "outside-allowlist.py"
            return draft
        assert "allowlist" in payload["validation_feedback"]
        return valid_patch(payload)

    model.handlers["patch"] = repairable_patch
    graph = build_goal_graph(model, checkpointer=InMemorySaver(), context_chars=4000)
    config = {"configurable": {"thread_id": "repair-patch"}}
    plan_gate = graph.invoke(initial_state(fixture_repo, fixture_task), config)

    patch_gate = graph.invoke(approve(interrupt_value(plan_gate)), config)

    assert interrupt_value(patch_gate)["gate"] == "patch"
    assert patch_calls == 2
    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == fixture_task["source"]
