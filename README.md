# Local Goal Loop

A local-model engineering loop built with LangGraph and llama.cpp: plan, approve,
patch, test, review, and stop at a bounded revision limit.

The host controls file access, hashes, approval gates, registered tests, SQLite
checkpoints, and completion. The model proposes structured plans, replacement
files, and reviews. A completion receipt proves only the supplied tests passed.

## What's here

- `src/graph_engineer/`, `tests/`, `fixtures/`: the engine and deterministic tests.
- `scripts/`: local server launch and evidence collection helpers.
- `evidence/2026-10-15-harness-fix/`: the earlier 7/10 → 9/10 fixture comparison.
- `experiments/LoopObservatory/`: the model-authored desktop prototype. **It failed
  acceptance: 20/24 tests passed; clicking and scrolling were broken.**
- `experiments/LoopObservatory-build/`: all seven build attempts, raw traces,
  checkpoints, screenshots, results, and the readable [model output transcript](experiments/LoopObservatory-build/MODEL-OUTPUTS.txt).
- [Handoff](experiments/LoopObservatory/HANDOFF.txt): exact defects and continuation steps.
- `docs/`: original specification, historical evaluation, and source README.

The Observatory experiment recorded 39 call records, 36,376 reported output tokens,
and 578.38 seconds summed ticket runtime. It was supervised and did not produce a
working app. The initial small test suite passing was insufficient evidence.

## Install and test

Requires Python 3.12 and uv. Run from this repository's root:

```powershell
uv sync --frozen
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

The root test command checks the engine. The preserved failing experiment has its
own tests, deliberately outside that suite:

Extraction verification: **115 engine tests passed**, lint passed, and all 20
engine/test/helper Python files passed the formatter check. No live model run was
made for this repository packaging step.

```powershell
Push-Location experiments/LoopObservatory
uv run --project ../.. python -m pytest -q tests
Pop-Location
```

Tkinter is required for the experiment. The original environment occasionally
failed while initializing multiple Tk roots; see the saved test-correction note.

## Run with a local model

Start your own llama.cpp server with a compatible GGUF model, then set the actual
endpoint and served alias. For the recorded session they were:

```powershell
$env:LOCAL_MODEL_BASE_URL = 'http://127.0.0.1:8089/v1'
$env:LOCAL_MODEL_NAME = 'qwen3.5-9b-q4km'
uv run graph-engineer demo --auto-approve
uv run graph-engineer evaluate --receipt-path .runtime/evaluation.json
```

The demo edits a temporary fixture. Omit `--auto-approve` to review its gates.
Server binaries, model weights, environments, and credentials are not included.
The older `probe` command and PowerShell server helpers use port 8080; the model
client uses `LOCAL_MODEL_BASE_URL`. `.env.example` documents settings but shell
commands require exported environment variables.

## Provenance

This repo was extracted from `langgraph/examples/local-graph-engineer` plus the
separate Observatory experiment. The engine now installs published LangGraph
1.2.11 instead of editable sibling paths; `uv.lock` pins the standalone resolution.
The historical collector paths were adjusted for this layout. The original
LangGraph checkout and all model-authored experiment code were left untouched.

Saved receipts contain historical local paths and PIDs; treat them as evidence,
not current runtime configuration. Some archived helper scripts retain original
workspace paths. The legacy historical source-hash gate predates this extraction.
Runtime traces may contain task/source text; this repository was created private.
