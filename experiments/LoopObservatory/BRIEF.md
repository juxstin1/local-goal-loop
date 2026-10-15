# Loop Observatory

Build a useful desktop flight recorder for local coding-agent runs, using only
Python standard-library modules and Tkinter. The product implementation belongs
to the local Qwen model. The host supplies this brief, stubs, samples, and tests.

## Files and contracts

`trace_reader.load_trace(path)` returns `(events, warnings)` from a UTF-8 JSONL
file. Read UTF-8 with an optional BOM. Ignore blank lines. Skip malformed JSON or
non-object rows and append a readable warning containing the 1-based line number.
Missing files raise FileNotFoundError; do not silently claim the file was empty.
Each accepted row becomes a dict with these fields:

- `line`: original 1-based line number; `role`: nonempty string or `unknown`.
- `attempt`: positive integer or 1. `tokens`: nonnegative integer output token
  count from response.usage_metadata.output_tokens, falling back to
  response.response_metadata.token_usage.completion_tokens, otherwise 0.
- `status`: `error` if row.error or row.error_type is truthy; otherwise
  `test-failed` if any dict in input.tests has an integer nonzero exit_code;
  otherwise `ok`. Malformed optional containers are treated as absent.
- `output`: readable Unicode text. For errors show the error text/type; otherwise
  show the first response.tool_calls entry's args as indented JSON, or the response
  content string, or an empty string. Do not eval anything in a trace.

`trace_metrics.summarize(events)` returns a new JSON-serializable dict containing
`calls`, `errors`, `failed_tests`, `repairs`, `output_tokens`, and `roles`.
Counts refer to recorded calls, not distinct test cases: repairs counts calls
whose attempt exceeds 1; roles maps role names to counts. Do not mutate events.

`observatory.Observatory(root)` is a tk.Frame packed by the caller. It exposes
`events`, `warnings`, `canvas` (tk.Canvas), `detail` (tk.Text), `summary_var`
(tk.StringVar), `load_file(path)`, `select_event(index)`, and
`export_summary(path)`. Loading replaces the previous trace; selecting a valid
event displays its role, status, and complete output. Invalid selections are
harmless. Export writes UTF-8 JSON with `summary` and `warnings` keys.

## Interface

Create a polished dark desktop window titled Loop Observatory, with a short
subtitle explaining that this is recorded agent activity. Show an Open trace
button, Export summary button, prominent counts, a horizontally scrollable canvas
of clickable event cards, a selection detail panel, and a readable warning count.
Color plan, patch, review, and error states distinctly. Make the current selected
card visibly different. Calls are ordered events, not measured elapsed time.
Opening or saving uses Tk file dialogs. File errors should be shown in the UI.
No network requests, browser dependencies, or external fonts are needed.

`main()` builds the window, uses a 1000x680 initial size, loads an optional first
command-line path or the bundled samples/demo.jsonl using __file__, and starts
mainloop. Keep imports safe: do not open a window at import time.
The main module must run with `python observatory.py`.

## Ticket scope

CORE: implement trace_reader.py and trace_metrics.py; registered pytest runs
tests/test_core.py. Leave observatory.py alone.
DESKTOP: implement observatory.py; registered pytest runs the entire tests folder
including CORE regressions. Other implementation files are read-only.
Do not change this brief, samples, or any test. The host controls file permissions.
