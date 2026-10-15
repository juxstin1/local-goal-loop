"""Host-owned probes not shown to the model during the original tickets."""
import json
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parent.parent / "LoopObservatory"
sys.path.insert(0, str(root))
from trace_reader import load_trace
from trace_metrics import summarize

cases = [
    ("non-container response", {"response": []}, {"tokens": 0, "output": ""}),
    ("non-container usage", {"response": {"usage_metadata": "bad"}}, {"tokens": 0}),
    ("non-container metadata", {"response": {"response_metadata": []}}, {"tokens": 0}),
    ("non-object tool call", {"response": {"tool_calls": [17]}}, {"output": ""}),
    ("non-container tests", {"input": {"tests": 42}}, {"status": "ok"}),
    ("non-integer exit", {"input": {"tests": [{"exit_code": "failed"}]}}, {"status": "ok"}),
    ("invalid role and attempt", {"role": ["plan"], "attempt": "two"}, {"role": "unknown", "attempt": 1}),
    ("negative tokens with fallback", {"response": {"usage_metadata": {"output_tokens": -1}, "response_metadata": {"token_usage": {"completion_tokens": 13}}}}, {"tokens": 13}),
    ("zero tokens takes precedence", {"response": {"usage_metadata": {"output_tokens": 0}, "response_metadata": {"token_usage": {"completion_tokens": 13}}}}, {"tokens": 0}),
    ("non-text content", {"response": {"content": [{"text": "hello"}]}}, {"output": ""}),
]
results = []
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "trace.jsonl"
    for name, row, expected in cases:
        path.write_text(json.dumps(row), encoding="utf-8")
        try:
            events, warnings = load_trace(path)
            actual = {key: events[0][key] for key in expected}
            summarize(events)
            results.append(dict(name=name,passed=actual==expected and not warnings,expected=expected,actual=actual))
        except Exception as error:
            results.append(dict(name=name,passed=False,error=f"{type(error).__name__}: {error}"))
for path in [root / "samples/demo.jsonl", *Path(__file__).parent.glob("*/trace.jsonl")]:
    try:
        events, warnings = load_trace(path)
        results.append(dict(name=str(path),passed=bool(events) and not warnings,summary=summarize(events)))
    except Exception as error:
        results.append(dict(name=str(path),passed=False,error=f"{type(error).__name__}: {error}"))
output = dict(passed=sum(r["passed"] for r in results),total=len(results),results=results)
dest = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name("holdouts.json")
dest.write_text(json.dumps(output,indent=2),encoding="utf-8")
print(json.dumps(output,indent=2))
sys.exit(0 if all(r["passed"] for r in results) else 1)
