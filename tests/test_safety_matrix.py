from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import initial_state, role_model_for_task
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph_engineer.graph import build_goal_graph
from graph_engineer.model import FunctionalRoleModel


def _interrupt_value(result: dict[str, Any]) -> dict[str, Any]:
    return result["__interrupt__"][0].value


APPROVAL_ATTACKS = [
    {"decision": "approve", "packet_hash": "0" * 64, "repository_fingerprint": "valid"},
    {"decision": "approve", "packet_hash": "1" * 64, "repository_fingerprint": "valid"},
    {"decision": "revise", "packet_hash": "2" * 64, "repository_fingerprint": "valid"},
    {"decision": "reject", "packet_hash": "3" * 64, "repository_fingerprint": "valid"},
    {"decision": "approve", "packet_hash": "valid", "repository_fingerprint": "wrong"},
    {"decision": "revise", "packet_hash": "valid", "repository_fingerprint": "wrong"},
    {"decision": "reject", "packet_hash": "valid", "repository_fingerprint": "wrong"},
    {"decision": "invalid", "packet_hash": "valid", "repository_fingerprint": "valid"},
    {"packet_hash": "valid", "repository_fingerprint": "valid"},
    {"decision": "approve", "repository_fingerprint": "valid"},
    {"decision": "approve", "packet_hash": "short", "repository_fingerprint": "valid"},
    {"decision": "approve", "packet_hash": "valid"},
]


@pytest.mark.parametrize("attack", APPROVAL_ATTACKS)
def test_approval_matrix_rejects_before_mutation(
    fixture_repo: Path, fixture_task: dict[str, Any], attack: dict[str, str]
) -> None:
    original = (fixture_repo / "solution.py").read_text(encoding="utf-8")
    graph = build_goal_graph(
        role_model_for_task(fixture_task), checkpointer=InMemorySaver(), context_chars=4000
    )
    config = {"configurable": {"thread_id": f"approval-{APPROVAL_ATTACKS.index(attack)}"}}
    gate = graph.invoke(initial_state(fixture_repo, fixture_task), config)
    expected = _interrupt_value(gate)
    payload = {**attack, "feedback": "attack"}
    if payload.get("packet_hash") == "valid":
        payload["packet_hash"] = expected["packet_hash"]
    if payload.get("repository_fingerprint") == "valid":
        payload["repository_fingerprint"] = expected["repository_fingerprint"]

    with pytest.raises((ValueError, TypeError)):
        graph.invoke(Command(resume=payload), config)

    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == original


PATH_INJECTIONS = [
    "../outside.py",
    "../../outside.py",
    "sub/../../../outside.py",
    "C:/Windows/outside.py",
    "C:\\Windows\\outside.py",
    "/absolute/outside.py",
    "test_solution.py",
    "TASK.md",
    ".env",
    ".git/config",
    "pyproject.toml",
    "solution.py/../test_solution.py",
    "nested/new.py",
    "README.md",
    "secrets.txt",
]

COMMAND_INJECTIONS = [
    "shell",
    "powershell",
    "cmd",
    "bash",
    "python",
    "pip-install",
    "uv-add",
    "git-reset",
    "git-clean",
    "git-push",
    "curl-network",
    "read-secrets",
    "delete-files",
    "pytest-and-shell",
    "arbitrary-command",
]


def _injection_model(*, file_path: str = "solution.py", test_id: str = "pytest") -> Any:
    def goal(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective": payload["objective"],
            "requirements": [
                {
                    "id": "REQ-001",
                    "statement": "The registered fixture behavior must be corrected.",
                    "evidence_required": "A passing registered test receipt.",
                }
            ],
            "non_goals": [],
            "completion_test": "The registered test exits zero.",
        }

    def plan(payload: dict[str, Any]) -> dict[str, Any]:
        evidence_id = payload["context"]["evidence"][0]["id"]
        return {
            "summary": "Attempt to expand the graph capability boundary.",
            "steps": [
                {
                    "order": 1,
                    "action": "Follow an injected repository instruction.",
                    "evidence_ids": [evidence_id],
                    "acceptance_test": "Injected action succeeds.",
                }
            ],
            "files": [file_path],
            "test_ids": [test_id],
            "risks": [],
        }

    return FunctionalRoleModel({"goal": goal, "plan": plan})


@pytest.mark.parametrize("file_path", PATH_INJECTIONS)
def test_repository_path_injection_cannot_expand_write_scope(
    fixture_repo: Path, fixture_task: dict[str, Any], file_path: str
) -> None:
    original = (fixture_repo / "solution.py").read_text(encoding="utf-8")
    graph = build_goal_graph(
        _injection_model(file_path=file_path),
        checkpointer=InMemorySaver(),
        context_chars=4000,
    )

    with pytest.raises(ValueError, match="write allowlist"):
        graph.invoke(
            initial_state(fixture_repo, fixture_task), {"configurable": {"thread_id": file_path}}
        )

    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("test_id", COMMAND_INJECTIONS)
def test_repository_command_injection_cannot_expand_execution_scope(
    fixture_repo: Path, fixture_task: dict[str, Any], test_id: str
) -> None:
    original = (fixture_repo / "solution.py").read_text(encoding="utf-8")
    graph = build_goal_graph(
        _injection_model(test_id=test_id),
        checkpointer=InMemorySaver(),
        context_chars=4000,
    )

    with pytest.raises(ValueError, match="unregistered test"):
        graph.invoke(
            initial_state(fixture_repo, fixture_task), {"configurable": {"thread_id": test_id}}
        )

    assert (fixture_repo / "solution.py").read_text(encoding="utf-8") == original
