from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from graph_engineer.fixture import load_tasks, materialize_task
from graph_engineer.graph import build_goal_graph
from graph_engineer.model import LocalChatRoleModel
from graph_engineer.packets import ApprovalDecision


def _interrupt_value(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    return interrupts[0].value


def _decision(
    value: dict[str, Any], auto_approve: bool, *, print_gate: bool = True
) -> dict[str, Any]:
    if print_gate:
        print(json.dumps(value, indent=2))
    if auto_approve:
        decision = ApprovalDecision.APPROVE
        feedback = "auto-approved fixture demonstration"
    else:
        answer = input("Decision [approve/revise/reject]: ").strip().lower()
        decision = ApprovalDecision(answer)
        feedback = input("Feedback (optional): ").strip()
    return {
        "decision": decision.value,
        "packet_hash": value["packet_hash"],
        "repository_fingerprint": value["repository_fingerprint"],
        "feedback": feedback,
    }


def _initial_state(task: dict[str, Any], root: Path, thread_id: str) -> dict[str, Any]:
    return {
        "objective": task["objective"],
        "repo_root": str(root),
        "task_id": task["id"],
        "thread_id": thread_id,
        "allowed_write_paths": ["solution.py"],
        "registered_test_ids": ["pytest"],
        "cycle_budget": 2,
        "iteration": 0,
        "status": "active",
        "repository_fingerprint": "pending",
        "events": [],
    }


def _execute_task(
    graph: Any,
    task: dict[str, Any],
    root: Path,
    *,
    auto_approve: bool,
    print_gates: bool,
) -> dict[str, Any]:
    thread_id = f"fixture-{task['id']}-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    current: Any = _initial_state(task, root, thread_id)
    while True:
        result = graph.invoke(current, config)
        value = _interrupt_value(result)
        if value is None:
            return {
                "task": task["id"],
                "final_receipt": result["final_receipt"],
                "resulting_source": (root / "solution.py").read_text(encoding="utf-8"),
            }
        current = Command(resume=_decision(value, auto_approve, print_gate=print_gates))


def _run_demo(auto_approve: bool, task_index: int, receipt_path: Path | None) -> int:
    task = load_tasks()[task_index]
    with tempfile.TemporaryDirectory(prefix="local-graph-engineer-") as temp:
        root = materialize_task(task, Path(temp) / "repo")
        checkpoint_path = Path(temp) / "checkpoints.sqlite"
        connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        try:
            graph = build_goal_graph(LocalChatRoleModel(), checkpointer=SqliteSaver(connection))
            receipt = _execute_task(graph, task, root, auto_approve=auto_approve, print_gates=True)
            rendered = json.dumps(receipt, indent=2)
            if receipt_path is not None:
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                receipt_path.write_text(rendered + "\n", encoding="utf-8")
            print(rendered, flush=True)
            return 0 if receipt["final_receipt"]["status"] == "complete" else 1
        finally:
            connection.close()


def _run_evaluation(receipt_path: Path) -> int:
    tasks = load_tasks()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    trace_dir = receipt_path.parent / f"{receipt_path.stem}-traces-{uuid.uuid4().hex[:8]}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    malformed_responses = 0
    with tempfile.TemporaryDirectory(prefix="local-graph-engineer-eval-") as temp:
        temp_root = Path(temp)
        connection = sqlite3.connect(trace_dir / "checkpoints.sqlite", check_same_thread=False)
        try:
            for index, task in enumerate(tasks):
                trace_path = trace_dir / f"{task['id']}.jsonl"
                model = LocalChatRoleModel(trace_path=trace_path)
                graph = build_goal_graph(model, checkpointer=SqliteSaver(connection))
                task_started = time.perf_counter()
                root = materialize_task(task, temp_root / f"repo-{index:02d}")
                try:
                    result = _execute_task(
                        graph,
                        task,
                        root,
                        auto_approve=True,
                        print_gates=False,
                    )
                    result["duration_ms"] = round((time.perf_counter() - task_started) * 1000)
                    result["matches_expected_fixture"] = (
                        result["resulting_source"] == task["expected_source"]
                    )
                except Exception as error:
                    result = {
                        "task": task["id"],
                        "duration_ms": round((time.perf_counter() - task_started) * 1000),
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "resulting_source": (root / "solution.py").read_text(encoding="utf-8"),
                    }
                malformed_responses += model.malformed_response_count
                result["trace_path"] = str(trace_path)
                result["malformed_response_count"] = model.malformed_response_count
                results.append(result)
                status = result.get("final_receipt", {}).get("status", "error")
                print(f"{task['id']}: {status}", flush=True)
        finally:
            connection.close()
    complete = sum(
        result.get("final_receipt", {}).get("status") == "complete" for result in results
    )
    receipt = {
        "fixture_count": len(tasks),
        "complete_count": complete,
        "pass_threshold": 7,
        "passed": complete >= 7,
        "clean_run": complete == len(tasks) and malformed_responses == 0,
        "malformed_response_count": malformed_responses,
        "checkpoint_path": str(trace_dir / "checkpoints.sqlite"),
        "verification_scope": "Unchanged registered fixture tests; no general autonomy claim.",
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in receipt.items() if key != "results"}, indent=2))
    return 0 if receipt["passed"] else 1


def _probe() -> int:
    with urlopen("http://127.0.0.1:8080/health", timeout=5) as response:
        health = json.load(response)
    with urlopen("http://127.0.0.1:8080/props", timeout=5) as response:
        props = json.load(response)
    print(
        json.dumps(
            {
                "health": health,
                "model_alias": props.get("model_alias"),
                "n_ctx": props.get("default_generation_settings", {}).get("n_ctx"),
                "total_slots": props.get("total_slots"),
                "tool_capabilities": props.get("chat_template_caps"),
            },
            indent=2,
        )
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local engineering goal loop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="Inspect the local llama-server")
    demo = subparsers.add_parser("demo", help="Run one frozen fixture through the loop")
    demo.add_argument("--auto-approve", action="store_true")
    demo.add_argument("--task-index", type=int, default=0, choices=range(10))
    demo.add_argument("--receipt-path", type=Path)
    evaluate = subparsers.add_parser("evaluate", help="Run all frozen fixtures")
    evaluate.add_argument(
        "--receipt-path", type=Path, default=Path(".runtime/live-evaluation.json")
    )
    args = parser.parse_args()
    if args.command == "probe":
        result = _probe()
    elif args.command == "evaluate":
        result = _run_evaluation(args.receipt_path)
    else:
        result = _run_demo(args.auto_approve, args.task_index, args.receipt_path)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
