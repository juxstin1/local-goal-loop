import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import traceback
import uuid

os.environ.update(LOCAL_MODEL_BASE_URL="http://127.0.0.1:8089/v1",
                  LOCAL_MODEL_NAME="qwen3.5-9b-q4km", LOCAL_MODEL_MAX_TOKENS="4096",
                  LOCAL_MODEL_PACKET_ATTEMPTS="3", LANGCHAIN_TRACING_V2="false",
                  LANGSMITH_TRACING="false", GOAL_LOOP_CONTEXT_CHARS="40000")
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from graph_engineer.cli import _interrupt_value
from graph_engineer.execution import COMMANDS, RegisteredCommand
from graph_engineer.graph import build_goal_graph
from graph_engineer.model import LocalChatRoleModel

root = Path(__file__).resolve().parent.parent / "LoopObservatory"
ticket = sys.argv[1]
if ticket.endswith("8K"):
    os.environ["LOCAL_MODEL_MAX_TOKENS"] = "8192"
out = Path(__file__).resolve().parent / ticket
out.mkdir(parents=True, exist_ok=False)
paths = ["trace_reader.py", "trace_metrics.py"] if ticket.startswith("CORE") else ["observatory.py"]
targets = ["tests/test_core.py"] if ticket == "CORE" else (["tests/test_core.py", "tests/test_robustness.py"] if ticket.startswith("CORE") else ["tests"])
COMMANDS["pytest"] = RegisteredCommand((sys.executable, "-m", "pytest", "-q", *targets), 60)
objective = (f"Complete ticket {ticket} of Loop Observatory exactly as BRIEF.md specifies. "
             f"Implement all behavior for this ticket in {', '.join(paths)}. "
             "Read the brief, existing source, and tests in the provided context. "
             "Make a usable, thoughtful tool with a complete implementation; leave protected files intact. "
             "Use compact code that fits the response limit. Run registered pytest and review its receipt.")
if len(sys.argv) > 2:
    objective += " Additional concrete feedback: " + sys.argv[2]
thread_id = f"observatory-{ticket}-{uuid.uuid4()}"
state = dict(objective=objective, repo_root=str(root), task_id=ticket, thread_id=thread_id,
             allowed_write_paths=paths, registered_test_ids=["pytest"], cycle_budget=2,
             iteration=0, status="active", repository_fingerprint="pending", events=[])
def hashes():
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in ('.pytest_cache', '__pycache__'))}
before = hashes()
(out / "initial.json").write_text(json.dumps({"state":state,"hashes":before,"max_output_tokens":int(os.environ["LOCAL_MODEL_MAX_TOKENS"])},indent=2),encoding="utf-8")
for path in paths:
    (out / (path + ".before")).write_bytes((root / path).read_bytes())
model = LocalChatRoleModel(trace_path=out / "trace.jsonl")
connection = sqlite3.connect(out / "checkpoints.sqlite", check_same_thread=False)
started = time.perf_counter()
receipt = {}
try:
    graph = build_goal_graph(model, checkpointer=SqliteSaver(connection))
    current = state
    while True:
        result = graph.invoke(current, {"configurable":{"thread_id":thread_id}})
        gate = _interrupt_value(result)
        if gate is None:
            receipt["final_receipt"] = result["final_receipt"]
            break
        with (out / "approvals.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(gate,default=str) + "\n")
        print(f"{ticket}: approving {gate.get('kind', gate.get('gate', 'bounded packet'))}",flush=True)
        current = Command(resume={"decision":"approve", "packet_hash":gate["packet_hash"],
                                  "repository_fingerprint":gate["repository_fingerprint"],
                                  "feedback":"User authorized local model build in isolated project; file allowlist enforced."})
except Exception as error:
    receipt.update(error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
finally:
    connection.close()
    receipt.update(duration_seconds=round(time.perf_counter()-started,2),hashes_after=hashes(),
                   malformed_response_count=model.malformed_response_count)
    for path in paths:
        (out / (path + ".after")).write_bytes((root / path).read_bytes())
    (out / "result.json").write_text(json.dumps(receipt,indent=2,default=str),encoding="utf-8")
    print(json.dumps(receipt,indent=2,default=str),flush=True)
sys.exit(0 if receipt.get("final_receipt",{}).get("status") == "complete" else 1)
