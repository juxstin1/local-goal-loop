from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from graph_engineer.fixture import load_tasks, materialize_task
from graph_engineer.model import FunctionalRoleModel


@pytest.fixture
def fixture_task() -> dict[str, Any]:
    return load_tasks()[0]


@pytest.fixture
def fixture_repo(tmp_path: Path, fixture_task: dict[str, Any]) -> Path:
    return materialize_task(fixture_task, tmp_path / "repo")


def role_model_for_task(
    task: dict[str, Any], *, first_patch_fails: bool = False
) -> FunctionalRoleModel:
    patch_calls = 0

    def goal(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective": payload["objective"],
            "requirements": [
                {
                    "id": "REQ-001",
                    "statement": task["objective"],
                    "evidence_required": "registered pytest receipt exits zero",
                }
            ],
            "non_goals": ["change function signature"],
            "completion_test": "REQ-001 is proved by the registered pytest receipt",
        }

    def solution_evidence(payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload["context"]["evidence"]
        return next(item for item in evidence if item["path"] == "solution.py")

    def plan(payload: dict[str, Any]) -> dict[str, Any]:
        evidence = solution_evidence(payload)
        return {
            "summary": "Correct the implementation and verify the registered tests.",
            "steps": [
                {
                    "order": 1,
                    "action": "Replace the incorrect implementation in solution.py.",
                    "evidence_ids": [evidence["id"]],
                    "acceptance_test": "pytest exits zero",
                }
            ],
            "files": ["solution.py"],
            "test_ids": ["pytest"],
            "risks": ["unrelated behavior must remain unchanged"],
        }

    def patch(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal patch_calls
        patch_calls += 1
        evidence = solution_evidence(payload)
        content = (
            task["source"] if first_patch_fails and patch_calls == 1 else task["expected_source"]
        )
        return {
            "summary": "Replace the broken implementation with the required behavior.",
            "replacements": [
                {
                    "path": "solution.py",
                    "expected_sha256": evidence["sha256"],
                    "content": content,
                }
            ],
            "test_ids": ["pytest"],
            "rationale": "The replacement directly satisfies the task and preserves the signature.",
        }

    def review(payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload["available_evidence"]
        test_evidence = next(item for item in evidence if item.startswith("test:pytest:"))
        passed = test_evidence.endswith("exit=0")
        return {
            "requirement_results": [
                {
                    "requirement_id": "REQ-001",
                    "status": "proved" if passed else "unproved",
                    "evidence": [test_evidence],
                    "explanation": "The registered test receipt passed."
                    if passed
                    else "The registered test receipt failed.",
                }
            ],
            "findings": [] if passed else ["The implementation still fails its test."],
            "next_action": (
                "finish" if passed else "Revise the implementation using the failure receipt."
            ),
        }

    return FunctionalRoleModel({"goal": goal, "plan": plan, "patch": patch, "review": review})


def initial_state(root: Path, task: dict[str, Any], *, cycle_budget: int = 2) -> dict[str, Any]:
    return {
        "objective": task["objective"],
        "repo_root": str(root),
        "task_id": task["id"],
        "thread_id": "test-thread",
        "allowed_write_paths": ["solution.py"],
        "registered_test_ids": ["pytest"],
        "cycle_budget": cycle_budget,
        "iteration": 0,
        "status": "active",
        "repository_fingerprint": "pending",
        "events": [],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
