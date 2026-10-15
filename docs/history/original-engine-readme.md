# Local Graph Engineer

This example implements a persistent engineering goal loop around a local
OpenAI-compatible `llama-server`:

```text
objective -> requirements -> evidence -> plan -> approval -> patch -> approval
          -> tests -> completion audit -> continue or finish
```

Python fixes the goal contract from the supplied objective and registered tests.
The model receives that contract, the existing test source, and write restrictions
before planning. It proposes plans, replacement files, and reviews; it cannot
redefine the test expectations or add completion requirements.

Python owns repository reads, original-file hashes, approvals, writes, test
execution, iteration budgets, and the final proof check. Completion means the
unchanged registered tests passed and their receipts were cited; it does not
claim exhaustive coverage of the objective. Protected-file fingerprints are
checked before and after test execution.

Tool schemas enumerate permitted paths and evidence references. The host fills
replacement hashes from the approved context. Malformed tool-JSON server errors
receive bounded corrective retries; unrelated server failures propagate.
Evaluation saves per-task model traces and SQLite checkpoints beside its receipt.
The existing `passed` field retains the seven-of-ten threshold; `clean_run`
additionally requires all ten completions and zero malformed-response errors.

## Setup

```powershell
cd examples/local-graph-engineer
uv sync
copy .env.example .env
uv run graph-engineer probe
uv run graph-engineer demo --auto-approve
```

`demo` materializes a frozen fixture in a temporary directory. It does not edit
the LangGraph checkout. Without `--auto-approve`, the CLI pauses at both approval
gates and displays the exact packet being approved.

## Verification

```powershell
make format
make lint
make test
```

The live probe and demo are separate from deterministic tests. A passing unit
suite does not claim that the currently served model can produce valid packets.

For a reproducible live proof that owns the server lifetime, use:

```powershell
.\scripts\run-live-demo.ps1 `
  -ServerExe $env:LLAMA_SERVER_EXE `
  -ModelPath $env:LOCAL_MODEL_PATH `
  -TaskIndex 0 `
  -ReceiptPath .runtime/live-demo-001.json
```

Run the complete ten-task gate under one owned server with:

```powershell
.\scripts\run-live-demo.ps1 `
  -ServerExe $env:LLAMA_SERVER_EXE `
  -ModelPath $env:LOCAL_MODEL_PATH `
  -Evaluate `
  -ReceiptPath .runtime/live-evaluation.json
```

Run the complete SPEC-000 protocol, safety, performance, stability, resource,
and source-hash matrix with:

```powershell
.\scripts\run-spec000-evidence.ps1 `
  -ServerExe $env:LLAMA_SERVER_EXE `
  -ModelPath $env:LOCAL_MODEL_PATH `
  -FixtureReceipt .runtime/live-evaluation-retry-2.json `
  -OutputDirectory ../../docs/proofs/spec-000-evidence/2026-08-22
```

The observed 2026-08-22 run passed the sealed evaluation objective. See
[`docs/proofs/SPEC-000-evaluation.md`](../../docs/proofs/SPEC-000-evaluation.md).
The broader SPEC-000 contract remains `draft`; its acceptance audit records the
unimplemented or unproved contract details separately from the passing receipt.
