"""Export saved model responses without making additional model calls."""
import json
from pathlib import Path

base = Path(__file__).resolve().parent
summary = json.loads((base / "build-summary.json").read_text(encoding="utf-8"))
parts = [
    "LOOP OBSERVATORY — RECORDED LOCAL MODEL OUTPUTS",
    "Model: " + summary["model"],
    f"Recorded output-token usage: {summary['output_tokens']:,}",
    f"Recorded call records: {summary['calls']}",
    "",
    "This is an export of the saved responses, not a newly generated account.",
    "Each response includes content, tool-call arguments, invalid partial tool calls,",
    "and returned metadata. Multiline strings (including source code) are expanded",
    "for reading. Tool arguments may appear both raw and parsed in the provider",
    "response; this file therefore is not itself a 36,376-token text sequence.",
    "The total is the sum of reported output-token usage, not input tokens.",
    "HTTP failures are preserved as errors. Output not returned by the server and",
    "internal provider retries cannot be reconstructed. Truncated text stays truncated.",
    "The prompts/context are in each ticket's trace.jsonl and in the combined",
    r"C:\Users\juxxs\Desktop\LoopObservatory\samples\self-build.jsonl.",
    "No model or product implementation was changed by this export.",
]

def render(value, indent=0):
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        lines = []
        for key, item in value.items():
            lines.append(pad + str(key) + ":")
            lines.extend(render(item, indent + 2))
        return lines
    if isinstance(value, list):
        if not value:
            return [pad + "[]"]
        lines = []
        for index, item in enumerate(value):
            lines.append(pad + f"[{index}]")
            lines.extend(render(item, indent + 2))
        return lines
    if isinstance(value, str) and "\n" in value:
        return [pad + "| (multiline string)", *[pad + "  " + line for line in value.split("\n")]]
    return [pad + json.dumps(value, ensure_ascii=False)]

count = 0
tokens = 0
errors = 0
for ticket in summary["tickets"]:
    name = ticket["ticket"]
    rows = [json.loads(line) for line in (base / name / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    parts.extend(["", "=" * 88, "TICKET: " + name, f"Recorded outcome: {ticket['status']}", "=" * 88])
    for row in rows:
        count += 1
        response = row.get("response")
        usage = (response or {}).get("usage_metadata", {})
        used = usage.get("output_tokens", 0)
        tokens += used
        parts.extend(["", "-" * 88,
                      f"RECORD {count:02d} | role={row.get('role')} | packet attempt={row.get('attempt')} | output tokens={used}",
                      "-" * 88])
        if response is not None:
            parts.extend(render(response))
        if row.get("error") or row.get("error_type"):
            errors += 1
            parts.extend(render({key: value for key, value in row.items() if key not in ("input", "response")}))
assert count == summary["calls"], (count, summary["calls"])
assert tokens == summary["output_tokens"], (tokens, summary["output_tokens"])
dest = base / "MODEL-OUTPUTS.txt"
dest.write_text("\n".join(parts) + "\n", encoding="utf-8")
print(json.dumps({"path": str(dest), "records": count, "reported_output_tokens": tokens,
                  "error_records": errors, "bytes": dest.stat().st_size}, indent=2))
