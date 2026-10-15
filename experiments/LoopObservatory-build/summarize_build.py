import hashlib
import json
from pathlib import Path

base = Path(__file__).resolve().parent
project = base.parent / "LoopObservatory"
names = ["CORE","DESKTOP","CORE-REPAIR","DESKTOP-REPAIR","DESKTOP-FINAL","DESKTOP-REBUILD","DESKTOP-REBUILD8K"]
rows = []
for name in names:
    result = json.loads((base/name/"result.json").read_text())
    trace = [json.loads(line) for line in (base/name/"trace.jsonl").read_text(encoding="utf-8").splitlines()]
    initial = json.loads((base/name/"initial.json").read_text())
    allowed = initial["state"]["allowed_write_paths"]
    changed = [path for path,digest in initial["hashes"].items() if result["hashes_after"].get(path)!=digest]
    rows.append(dict(ticket=name,max_output_tokens=initial.get("max_output_tokens",4096),status=result.get("final_receipt",{}).get("status","error"),
                     iterations=result.get("final_receipt",{}).get("iterations_completed"),
                     seconds=result["duration_seconds"],calls=len(trace),
                     output_tokens=sum(r.get("response",{}).get("usage_metadata",{}).get("output_tokens",0) for r in trace),
                     malformed_responses=result["malformed_response_count"],changed_files=changed,
                     protected_files_unchanged=all(path in allowed for path in changed)))
output = dict(model="Qwen3.5-9B-Q4_K_M",runtime="llama.cpp local port 8089",max_output_tokens_per_call="4096 initially; 8192 for DESKTOP-REBUILD8K",
              outcome="failed acceptance: 20 of 24 tests passed; visible click and scroll checks failed",
              tickets=rows,seconds=sum(r["seconds"] for r in rows),calls=sum(r["calls"] for r in rows),
              output_tokens=sum(r["output_tokens"] for r in rows),
              authorship="Qwen authored all three implementation files. Codex supplied brief, stubs, tests, feedback, runner, sample assembly, launcher, and documentation.",
              qualification="Initial ticket passes were insufficient: external probes exposed parsing and usability gaps. Repair tickets used additional tests. This is a supervised build, not an unaided success.",
              source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in project.glob("*.py")})
(base/"build-summary.json").write_text(json.dumps(output,indent=2),encoding="utf-8")
print(json.dumps(output,indent=2))
