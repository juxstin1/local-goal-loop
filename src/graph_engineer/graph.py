from __future__ import annotations

import difflib
import operator
import os
from pathlib import Path
from typing import Annotated, Any, NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph_engineer.context import build_context, repository_fingerprint, resolve_inside
from graph_engineer.execution import (
    COMMANDS,
    apply_replacements,
    run_registered_test,
    validate_replacements,
)
from graph_engineer.model import LocalChatRoleModel, RoleModel
from graph_engineer.packets import (
    Approval,
    ApprovalDecision,
    ContextPacket,
    FileReplacement,
    GoalContract,
    PacketEnvelope,
    PatchDraft,
    PlanDraft,
    Requirement,
    ReviewDraft,
    envelope,
)

MAX_REVISIONS = 1


class GoalLoopState(TypedDict):
    objective: str
    repo_root: str
    task_id: str
    thread_id: str
    allowed_write_paths: list[str]
    registered_test_ids: list[str]
    cycle_budget: int
    iteration: int
    status: str
    repository_fingerprint: str
    protected_fingerprint: NotRequired[str]
    goal: NotRequired[dict[str, Any]]
    context: NotRequired[dict[str, Any]]
    plan: NotRequired[dict[str, Any]]
    patch: NotRequired[dict[str, Any]]
    plan_approval: NotRequired[dict[str, Any]]
    patch_approval: NotRequired[dict[str, Any]]
    tests: NotRequired[list[dict[str, Any]]]
    review: NotRequired[dict[str, Any]]
    final_receipt: NotRequired[dict[str, Any]]
    feedback: NotRequired[str]
    events: Annotated[list[dict[str, Any]], operator.add]


def _event(stage: str, **data: Any) -> list[dict[str, Any]]:
    return [{"stage": stage, **data}]


def _packet(state: GoalLoopState, key: str) -> PacketEnvelope:
    return PacketEnvelope.model_validate(state[key])


def _approval(value: Any, expected: PacketEnvelope) -> Approval:
    approval = Approval.model_validate(value)
    if approval.packet_hash != expected.packet_hash:
        raise ValueError("approval packet hash does not match")
    if approval.repository_fingerprint != expected.repository_fingerprint:
        raise ValueError("approval repository fingerprint does not match")
    return approval


def _make_diff(root: Path, replacements: tuple[FileReplacement, ...]) -> str:
    chunks: list[str] = []
    for replacement in replacements:
        path = resolve_inside(root, replacement.path)
        before = path.read_text(encoding="utf-8").splitlines(keepends=True)
        after = replacement.content.splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{replacement.path}",
                tofile=f"b/{replacement.path}",
            )
        )
    return "".join(chunks)


def build_goal_graph(
    model: RoleModel | None = None,
    *,
    checkpointer: Any | None = None,
    context_chars: int | None = None,
) -> Any:
    role_model = model or LocalChatRoleModel()
    context_budget = context_chars or int(os.getenv("GOAL_LOOP_CONTEXT_CHARS", "8000"))

    def intake(state: GoalLoopState) -> dict[str, Any]:
        root = Path(state["repo_root"]).resolve()
        if not root.is_dir():
            raise ValueError(f"repository does not exist: {root}")
        if not state["allowed_write_paths"]:
            raise ValueError("at least one writable path is required")
        for relative in state["allowed_write_paths"]:
            path = resolve_inside(root, relative)
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"writable path must be a regular file: {relative}")
        fingerprint = repository_fingerprint(root)
        test_ids = state["registered_test_ids"]
        if not test_ids or len(test_ids) > 12 or len(set(test_ids)) != len(test_ids):
            raise ValueError("one to twelve distinct registered tests are required")
        if not set(test_ids) <= set(COMMANDS):
            raise ValueError("goal requests an unregistered test")
        # Acceptance belongs to the host. The model cannot invent requirements or
        # reinterpret frozen tests before seeing their source in gather_context.
        goal = GoalContract(
            objective=state["objective"],
            requirements=tuple(
                Requirement(
                    id=f"REQ-{index:03d}",
                    statement=f"The unchanged registered {test_id} tests pass for this objective.",
                    evidence_required=f"test:{test_id}:exit=0",
                )
                for index, test_id in enumerate(test_ids, 1)
            ),
            non_goals=(
                "Change tests or their expectations",
                "Claim coverage beyond supplied tests",
            ),
            completion_test="All registered tests pass unchanged; scope is supplied tests only.",
        )
        packet = envelope(
            kind="goal",
            task_id=state["task_id"],
            thread_id=state["thread_id"],
            iteration=0,
            repository_fingerprint=fingerprint,
            payload=goal,
        )
        return {
            "iteration": 0,
            "status": "active",
            "repository_fingerprint": fingerprint,
            "protected_fingerprint": repository_fingerprint(
                root, exclude_paths=tuple(state["allowed_write_paths"])
            ),
            "goal": packet.model_dump(mode="json"),
            "events": _event("intake", packet_hash=packet.packet_hash),
        }

    def gather_context(state: GoalLoopState) -> dict[str, Any]:
        context = build_context(Path(state["repo_root"]), budget_chars=context_budget)
        packet = envelope(
            kind="context",
            task_id=state["task_id"],
            thread_id=state["thread_id"],
            iteration=state["iteration"],
            repository_fingerprint=context.repository_fingerprint,
            payload=context,
        )
        return {
            "repository_fingerprint": context.repository_fingerprint,
            "context": packet.model_dump(mode="json"),
            "events": _event(
                "context",
                packet_hash=packet.packet_hash,
                used_chars=context.used_chars,
                truncated=context.truncated,
            ),
        }

    def draft_plan(state: GoalLoopState) -> dict[str, Any]:
        context_packet = _packet(state, "context")
        context = ContextPacket.model_validate(context_packet.payload)
        payload = {
            "objective": state["objective"],
            "goal": _packet(state, "goal").payload,
            "context": context.model_dump(mode="json"),
            "allowed_write_paths": state["allowed_write_paths"],
            "registered_test_ids": state["registered_test_ids"],
            "iteration": state["iteration"],
            "previous_review": state.get("review"),
            "previous_tests": state.get("tests", []),
            "human_feedback": state.get("feedback", ""),
        }
        evidence_ids = {item.id for item in context.evidence}
        last_error: ValueError | None = None
        for attempt in range(2):
            plan = role_model.invoke("plan", PlanDraft, payload)
            try:
                if any(not set(step.evidence_ids) <= evidence_ids for step in plan.steps):
                    raise ValueError("plan cites evidence outside the context packet")
                if not set(plan.files) <= set(state["allowed_write_paths"]):
                    raise ValueError("plan requests a file outside the write allowlist")
                if not set(plan.test_ids) <= set(state["registered_test_ids"]):
                    raise ValueError("plan requests an unregistered test")
                break
            except ValueError as error:
                last_error = error
                if attempt == 1:
                    raise
                payload["validation_feedback"] = str(error)
                payload["rejected_draft"] = plan.model_dump(mode="json")
                payload["allowed_evidence_ids"] = sorted(evidence_ids)
                payload["invalid_evidence_ids"] = sorted(
                    {ref for step in plan.steps for ref in step.evidence_ids} - evidence_ids
                )
                payload["invalid_files"] = sorted(
                    set(plan.files) - set(state["allowed_write_paths"])
                )
                payload["invalid_test_ids"] = sorted(
                    set(plan.test_ids) - set(state["registered_test_ids"])
                )
        else:
            raise AssertionError(f"unreachable plan repair state: {last_error}")
        packet = envelope(
            kind="plan",
            task_id=state["task_id"],
            thread_id=state["thread_id"],
            iteration=state["iteration"],
            repository_fingerprint=state["repository_fingerprint"],
            payload=plan,
        )
        return {
            "plan": packet.model_dump(mode="json"),
            "feedback": "",
            "events": _event("plan", packet_hash=packet.packet_hash),
        }

    def plan_approval(state: GoalLoopState) -> dict[str, Any]:
        expected = _packet(state, "plan")
        resumed = interrupt(
            {
                "gate": "plan",
                "packet_hash": expected.packet_hash,
                "repository_fingerprint": expected.repository_fingerprint,
                "iteration": state["iteration"],
                "plan": expected.payload,
            }
        )
        approval = _approval(resumed, expected)
        return {
            "plan_approval": approval.model_dump(mode="json"),
            "feedback": approval.feedback,
            "status": "rejected" if approval.decision == ApprovalDecision.REJECT else "active",
            "events": _event("plan_approval", decision=approval.decision.value),
        }

    def draft_patch(state: GoalLoopState) -> dict[str, Any]:
        context = ContextPacket.model_validate(_packet(state, "context").payload)
        payload = {
            "objective": state["objective"],
            "goal": _packet(state, "goal").payload,
            "approved_plan": _packet(state, "plan").payload,
            "context": context.model_dump(mode="json"),
            "previous_review": state.get("review"),
            "previous_tests": state.get("tests", []),
            "human_feedback": state.get("feedback", ""),
        }
        plan = PlanDraft.model_validate(_packet(state, "plan").payload)
        last_error: ValueError | None = None
        for attempt in range(2):
            patch = role_model.invoke("patch", PatchDraft, payload)
            try:
                validate_replacements(
                    Path(state["repo_root"]),
                    patch.replacements,
                    set(plan.files),
                )
                if not set(patch.test_ids) <= set(plan.test_ids):
                    raise ValueError("patch requests a test outside the approved plan")
                break
            except ValueError as error:
                last_error = error
                if attempt == 1:
                    raise
                payload["validation_feedback"] = str(error)
                payload["rejected_draft"] = patch.model_dump(mode="json")
                payload["approved_write_paths"] = list(plan.files)
        else:
            raise AssertionError(f"unreachable patch repair state: {last_error}")
        payload = {
            "draft": patch.model_dump(mode="json"),
            "unified_diff": _make_diff(Path(state["repo_root"]), patch.replacements),
        }
        packet = envelope(
            kind="patch",
            task_id=state["task_id"],
            thread_id=state["thread_id"],
            iteration=state["iteration"],
            repository_fingerprint=state["repository_fingerprint"],
            payload=payload,
        )
        return {
            "patch": packet.model_dump(mode="json"),
            "feedback": "",
            "events": _event("patch", packet_hash=packet.packet_hash),
        }

    def patch_approval(state: GoalLoopState) -> dict[str, Any]:
        expected = _packet(state, "patch")
        resumed = interrupt(
            {
                "gate": "patch",
                "packet_hash": expected.packet_hash,
                "repository_fingerprint": expected.repository_fingerprint,
                "iteration": state["iteration"],
                "summary": expected.payload["draft"]["summary"],
                "unified_diff": expected.payload["unified_diff"],
                "test_ids": expected.payload["draft"]["test_ids"],
            }
        )
        approval = _approval(resumed, expected)
        return {
            "patch_approval": approval.model_dump(mode="json"),
            "feedback": approval.feedback,
            "status": "rejected" if approval.decision == ApprovalDecision.REJECT else "active",
            "events": _event("patch_approval", decision=approval.decision.value),
        }

    def apply_patch(state: GoalLoopState) -> dict[str, Any]:
        expected = _packet(state, "patch")
        if repository_fingerprint(Path(state["repo_root"])) != expected.repository_fingerprint:
            raise ValueError("repository changed after patch approval")
        patch = PatchDraft.model_validate(expected.payload["draft"])
        validate_replacements(
            Path(state["repo_root"]),
            patch.replacements,
            set(PlanDraft.model_validate(_packet(state, "plan").payload).files),
        )
        apply_replacements(Path(state["repo_root"]), patch.replacements)
        fingerprint = repository_fingerprint(Path(state["repo_root"]))
        return {
            "repository_fingerprint": fingerprint,
            "events": _event("apply", packet_hash=expected.packet_hash),
        }

    def run_tests(state: GoalLoopState) -> dict[str, Any]:
        root = Path(state["repo_root"])

        def check_protected_files() -> None:
            if (
                repository_fingerprint(root, exclude_paths=tuple(state["allowed_write_paths"]))
                != state["protected_fingerprint"]
            ):
                raise ValueError("protected files changed; test evidence is invalid")

        check_protected_files()
        patch = PatchDraft.model_validate(_packet(state, "patch").payload["draft"])
        receipts = [
            run_registered_test(Path(state["repo_root"]), command_id).model_dump(mode="json")
            for command_id in patch.test_ids
        ]
        check_protected_files()
        return {
            "tests": receipts,
            "events": _event(
                "tests",
                passed=all(receipt["exit_code"] == 0 for receipt in receipts),
                command_ids=[receipt["command_id"] for receipt in receipts],
            ),
        }

    def completion_audit(state: GoalLoopState) -> dict[str, Any]:
        post_context = build_context(Path(state["repo_root"]), budget_chars=context_budget)
        available_evidence = {
            *(
                f"test:{receipt['command_id']}:exit={receipt['exit_code']}"
                for receipt in state["tests"]
            ),
            *(f"file:{item.path}:sha256={item.sha256}" for item in post_context.evidence),
        }
        review = role_model.invoke(
            "review",
            ReviewDraft,
            {
                "objective": state["objective"],
                "goal": _packet(state, "goal").payload,
                "plan": _packet(state, "plan").payload,
                "patch_hash": _packet(state, "patch").packet_hash,
                "tests": state["tests"],
                "post_change_context": post_context.model_dump(mode="json"),
                "available_evidence": sorted(available_evidence),
                "completion_rule": (
                    "Every requirement proved, every cited receipt real, all tests pass."
                ),
            },
        )
        goal = GoalContract.model_validate(_packet(state, "goal").payload)
        by_requirement = {result.requirement_id: result for result in review.requirement_results}
        every_requirement_proved = all(
            requirement.id in by_requirement
            and by_requirement[requirement.id].status == "proved"
            and bool(by_requirement[requirement.id].evidence)
            and set(by_requirement[requirement.id].evidence) <= available_evidence
            and requirement.evidence_required in by_requirement[requirement.id].evidence
            for requirement in goal.requirements
        )
        tests_passed = {receipt["command_id"] for receipt in state["tests"]} == set(
            state["registered_test_ids"]
        ) and all(receipt["exit_code"] == 0 for receipt in state["tests"])
        complete = every_requirement_proved and tests_passed
        payload = {
            "model_review": review.model_dump(mode="json"),
            "complete": complete,
            "tests_passed": tests_passed,
            "every_requirement_proved": every_requirement_proved,
            "available_evidence": sorted(available_evidence),
            "verification_scope": "Unchanged registered tests only; coverage is not exhaustive.",
        }
        packet = envelope(
            kind="completion_audit",
            task_id=state["task_id"],
            thread_id=state["thread_id"],
            iteration=state["iteration"],
            repository_fingerprint=post_context.repository_fingerprint,
            payload=payload,
        )
        status = "complete" if complete else "active"
        if not complete and state["iteration"] >= MAX_REVISIONS:
            status = "revision_cap_reached"
        return {
            "review": packet.model_dump(mode="json"),
            "status": status,
            "events": _event("completion_audit", complete=complete, packet_hash=packet.packet_hash),
        }

    def advance_iteration(state: GoalLoopState) -> dict[str, Any]:
        return {
            "iteration": state["iteration"] + 1,
            "status": "active",
            "events": _event("continue", next_iteration=state["iteration"] + 1),
        }

    def final_receipt(state: GoalLoopState) -> dict[str, Any]:
        review = _packet(state, "review").payload if "review" in state else None
        receipt = {
            "objective": state["objective"],
            "status": state["status"],
            "iterations_completed": state["iteration"] + 1,
            "goal_hash": _packet(state, "goal").packet_hash,
            "goal_contract": _packet(state, "goal").payload,
            "last_review_hash": _packet(state, "review").packet_hash if "review" in state else None,
            "tests": state.get("tests", []),
            "review": review,
            "next_action": None
            if state["status"] == "complete"
            else state.get("feedback") or "Resume the active goal loop with more evidence.",
        }
        return {
            "final_receipt": receipt,
            "events": _event("final", status=state["status"]),
        }

    def route_plan_approval(state: GoalLoopState) -> str:
        decision = Approval.model_validate(state["plan_approval"]).decision
        if decision == ApprovalDecision.APPROVE:
            return "draft_patch"
        if decision == ApprovalDecision.REVISE:
            return "draft_plan"
        return "final_receipt"

    def route_patch_approval(state: GoalLoopState) -> str:
        decision = Approval.model_validate(state["patch_approval"]).decision
        if decision == ApprovalDecision.APPROVE:
            return "apply_patch"
        if decision == ApprovalDecision.REVISE:
            return "draft_patch"
        return "final_receipt"

    def route_audit(state: GoalLoopState) -> str:
        if state["status"] == "complete":
            return "final_receipt"
        if state["iteration"] < MAX_REVISIONS:
            return "advance_iteration"
        return "final_receipt"

    builder = StateGraph(GoalLoopState)
    builder.add_node("intake", intake)
    builder.add_node("gather_context", gather_context)
    builder.add_node("draft_plan", draft_plan)
    builder.add_node("plan_approval", plan_approval)
    builder.add_node("draft_patch", draft_patch)
    builder.add_node("patch_approval", patch_approval)
    builder.add_node("apply_patch", apply_patch)
    builder.add_node("run_tests", run_tests)
    builder.add_node("completion_audit", completion_audit)
    builder.add_node("advance_iteration", advance_iteration)
    builder.add_node("final_receipt", final_receipt)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "gather_context")
    builder.add_edge("gather_context", "draft_plan")
    builder.add_edge("draft_plan", "plan_approval")
    builder.add_conditional_edges("plan_approval", route_plan_approval)
    builder.add_edge("draft_patch", "patch_approval")
    builder.add_conditional_edges("patch_approval", route_patch_approval)
    builder.add_edge("apply_patch", "run_tests")
    builder.add_edge("run_tests", "completion_audit")
    builder.add_conditional_edges("completion_audit", route_audit)
    builder.add_edge("advance_iteration", "gather_context")
    builder.add_edge("final_receipt", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


graph = build_goal_graph()
