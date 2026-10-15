"""Host packaging only; never changes model-authored implementation."""
from pathlib import Path
import json

base = Path(__file__).resolve().parent
root = base.parent / "LoopObservatory"
names = ["CORE","DESKTOP","CORE-REPAIR","DESKTOP-REPAIR","DESKTOP-FINAL","DESKTOP-REBUILD","DESKTOP-REBUILD8K"]
lines = []
for name in names:
    lines.extend((base/name/"trace.jsonl").read_text(encoding="utf-8").splitlines())
(root/"samples/self-build.jsonl").write_text("\n".join(lines)+"\n",encoding="utf-8")
(root/"Launch.cmd").write_text('@echo off\ncd /d "%~dp0"\npy -3 observatory.py "%~dp0samples\\self-build.jsonl"\nif errorlevel 1 pause\n',encoding="ascii")
summary = json.loads((base/"build-summary.json").read_text())
(root/"README.txt").write_text('''Loop Observatory - FAILED BUILD EXPERIMENT

Final acceptance: 20 of 24 tests passed. The 16 parser/metrics tests passed.
Actual window check: clicking a card failed with TclError for -outline_width;
horizontal scrolling did not move. Programmatic JSON export worked (6 calls).
The screenshot also shows overlapping, low-contrast headings and wasted space.
This is an inspectable prototype, not a successfully completed application.

A local desktop viewer for the recorded plans, patches, reviews, and failures of
the coding loop. The included self-build trace is the actual sequence of model
calls that produced this tool, including unsuccessful attempts.

Launch: double-click Launch.cmd (Python 3 with Tkinter required).
Alternatively: python observatory.py samples/self-build.jsonl
No model server, network, or third-party package is needed to use the viewer.

Intended behavior: open a JSONL trace, click cards to inspect output, scroll to
later calls, and export counts. Clicking and scrolling remain broken. File-dialog
callbacks also reference tkinter.filedialog without importing it; the missing-file
handler calls an undefined _update_ui method. These are model implementation bugs.
Cards are ordered calls, not an elapsed-time chart. An error is a recorded call error; a failed-test event is a
call whose input contains a nonzero test exit code. Counts are per call.

The exported "repairs" field counts packet attempts greater than 1, not code
revision cycles. The trace format does not put the revision cycle in that field.
Some runtime-internal retries are absent from these traces. Input test diagnostics
are retained in the JSONL files; the viewer shows the recorded response output.

Authorship: local Qwen3.5-9B-Q4_K_M wrote trace_reader.py, trace_metrics.py, and
observatory.py. Codex supplied the idea, brief, empty stubs, tests, concrete repair
feedback, runtime runner, packaging, and validation. This was a supervised build.
After repeated interface repair failures, the host preserved that source and
restored the original empty stub for a clean local-model rewrite.

Original tests were preserved. Additional tests were added after independent
failures; one added test's parent-widget assumption was corrected transparently.
All attempts, checkpoints, hashes, and results are in the neighboring
LoopObservatory-build folder. See build-summary.json and TEST-CORRECTION.md.

Other scope limits: small local traces loaded in memory; no background loading,
live recording, editing, or code execution. Tests cover supplied cases, not every
possible JSON type combination. The parser currently preserves an empty role
string instead of converting it to "unknown", and JSON-embedded Unicode may be
shown with escape sequences. Treat it as an experimental tool.

''' + json.dumps(summary,indent=2) + '\n',encoding="utf-8")
print(f"Packaged {len(lines)} recorded calls; implementation untouched.")
