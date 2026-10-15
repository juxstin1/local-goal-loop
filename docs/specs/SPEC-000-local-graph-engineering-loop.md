---
title: "SPEC-000: Local Graph Engineering Loop"
status: draft
date: 2026-08-22
scope: "Draft contract plus a validated Qwen-powered engineering-loop candidate operating on frozen fixtures."
owners: [user]
related: [ADR-0001, TICKET-001]
packages: [langgraph, langchain, langchain-openai]
---

# SPEC-000: Local Graph Engineering Loop

> Build a checkpointed engineering workflow in which narrow model roles exchange
> typed artifacts, the host validates every handoff, and failed evidence returns
> through a bounded revision loop.

## Problem

Conversational agent handoffs lose scope, evidence, repository revision, and test
results. A small local model is especially likely to drift when it must remember
the entire engineering process, select among many tools, and decide its own retry
policy. The workflow needs explicit ownership and machine-checked transitions.

## Current State Evidence

Observed on 2026-08-22. Machine facts require rechecking before reuse; the sealed
receipt remains historical evidence for that run.

| Area | Evidence |
| --- | --- |
| Checkout | Dirty `main`; the docs and `examples/local-graph-engineer/` candidate are untracked, and `.gitignore` is modified |
| Host | Ryzen 7 9800X3D, 32 GB RAM, Radeon RX 9070 XT with 16 GB VRAM |
| Candidate | Direct `StateGraph`, typed Pydantic packets, deterministic context, two approvals, host mutation/tests, and one absolute revision are implemented under `examples/local-graph-engineer/` |
| Server | `llama-server` build 10079 was run as one owned slot on `127.0.0.1:8080` |
| Model | Qwen3.5-9B Q4_K_M, Apache-2.0; SHA-256 `cd76ec205963b3b33350093e6904d9de16c4e666fd104e1f632d25c7f15f2a13` |
| Template | `/props` recorded a nonempty Jinja template with tool and tool-call support |
| Context | One 32,768-token slot; measured evaluation input was 2,048 tokens, or 6.25% |
| Sealed objective | Pass: 10/10 raw calls, 20/20 selections, 8/10 fixtures, all requested safety gates, 20/20 stability, and all runtime thresholds |
| Contract status | `draft`; user acceptance is pending, and the acceptance audit below contains unproved or divergent items |

The sealed receipt is `docs/proofs/SPEC-000-evaluation.md`. It proves the stated
evaluation objective, not every sentence of this still-draft contract.

## Goals

- Teach graph engineering through visible state, nodes, edges, interrupts,
  checkpoints, subgraphs, and bounded revision routes.
- Carry scope, evidence, plan, patch, tests, and review verdicts through typed
  handoff packets rather than conversational summaries.
- Prove one small change against one frozen fixture repository.
- Require separate human approval of the plan and the exact patch.
- Keep model access read-only; mutation and tests are deterministic host nodes.

## Non-Goals

- Multiple repositories, model bake-offs, subagent spawning, or Deep Agents.
- Arbitrary shell, network, package installation, credentials, deletion, Git
  history rewriting, pushing, or deployment.
- Autonomous project development or a claim that passing tests proves code
  quality.

## Proposed Design

### Graph

```text
intake_and_guard
  -> reconnaissance
  -> validate_evidence
  -> draft_plan
  -> validate_plan
  -> plan_approval_interrupt
       reject -> final_receipt
       revise -> draft_plan
       approve -> draft_patch
  -> validate_patch
  -> patch_approval_interrupt
       reject -> final_receipt
       revise -> draft_patch
       approve -> apply_exact_patch
  -> run_registered_tests
  -> independent_review
       pass -> final_receipt
       fail and revision_count < 1 -> revision_packet -> draft_patch
       fail at cap -> final_receipt
```

Every revised patch returns through validation and a fresh patch approval. No
model response can jump an edge or invoke mutation directly.

### Ownership

| Owner | Exact responsibility |
| --- | --- |
| Human | Task meaning, fixture selection, plan approval, patch approval |
| LangGraph | State, transition order, checkpoint, interrupt, retry cap |
| Qwen model | Goal, plan, patch, and review packet drafts from host-provided evidence |
| Host tools | Canonical paths, reads, schema validation, patch application, tests |

### Handoff contracts

All packets include `task_id`, `thread_id`, `producer`, `created_at`,
`base_revision`, `workspace_fingerprint`, `schema_version`, and `status`.

| Packet | Required payload |
| --- | --- |
| `ScopePacket` | Request, repository root, read/write allowlists, registered test IDs |
| `EvidencePacket` | Query, file/line references, excerpts, truncation flags, gaps |
| `PlanPacket` | Summary, intended files, ordered changes, test IDs, risks |
| `ApprovalPacket` | Decision, packet hash, workspace fingerprint, feedback |
| `PatchPacket` | Unified diff, base revision, plan hash, rationale, test IDs |
| `TestReceipt` | Command ID, argv, exit code, duration, bounded output, timestamp |
| `ReviewVerdict` | Pass/fail, findings with evidence, required revision |
| `FinalReceipt` | Outcome, packet hashes, tests, revisions, unresolved work |

The handoff validator rejects missing fields, stale revisions, mismatched hashes,
paths outside the fixture, unregistered test IDs, silent truncation, and packets
from the wrong thread. Invalid handoffs return once to their producer; a second
invalid handoff ends the run with a typed failure.

### Model and discovery subgraph

`langchain_openai.ChatOpenAI` connects to
`http://127.0.0.1:8080/v1` with the server-reported model alias,
`temperature=0`, `timeout=120`, `max_retries=1`, and Chat Completions mode.
The implementation must not store a secret because local llama.cpp authentication
is disabled; the client receives a documented non-secret placeholder value.

The LangChain discovery subgraph exposes only:

- `list_files(glob, max_results <= 200)`
- `search_code(query, path_globs, max_matches <= 80)`
- `read_file(path, start_line, max_lines <= 300)`

It is capped at six model calls and twelve tool calls. Patch generation and
review receive validated packets but no tools.

### Observed candidate deviations

The candidate does not silently satisfy the proposed design above:

- `context.py` builds one bounded context packet deterministically. No live
  `create_agent`, `list_files`, `search_code`, or `read_file` discovery tool is
  present. ADR-0001 records the implemented architecture; accepting it as the
  contract requires a user-reviewed spec revision.
- `PacketEnvelope` carries `kind`, `task_id`, `thread_id`, `iteration`,
  `repository_fingerprint`, `payload`, and `packet_hash`. It does not implement
  every envelope field listed in the draft handoff contract.
- The approved patch view is a unified diff, but the host applies validated,
  atomic whole-file replacements after SHA-256 checks. It does not run
  `git apply --check` or apply a model-provided diff.
- Evaluation fixtures are materialized in temporary directories, not isolated
  Git worktrees, and the candidate does not enforce a clean Git start.
- The candidate and fixture bundle are untracked. The proof records the base Git
  revision plus an authoritative per-file source manifest, not graph and fixture
  commits.
- Raw `add(17, 25)` calls passed 10/10, and live graph roles use
  `ChatOpenAI.bind_tools`; a standalone LangChain `add(17, 25) -> 42` completion
  receipt was not sealed.

### Containment

- Operate on a frozen fixture in an isolated Git worktree.
- Fail closed on a dirty start, symlink escape, path traversal, repository drift,
  changed approval hash, malformed diff, or out-of-allowlist path.
- Run `git apply --check` before applying the exact approved diff.
- Tests use registered command IDs mapped to fixed argv arrays, working directory,
  timeout, and output limit; no free-form command string is accepted.
- Prohibit deletes and destructive Git commands in Spec 0.
- Persist checkpoints to SQLite; use in-memory persistence only in unit tests.

## File Touchpoints

| File or area | Action | Reason |
| --- | --- | --- |
| `examples/local-graph-engineer/` | Contains untracked uv application candidate | Keep framework libraries untouched |
| `examples/local-graph-engineer/fixtures/` | Contains ten frozen change tasks | Repeatable local evaluation |
| `docs/proofs/SPEC-000-evaluation.md` | Contains sealed observed receipt | Separate evidence from design claims |

## API Or Data Contract

Packets are frozen Pydantic models with `extra="forbid"`. Packet hashes are
SHA-256 over canonical JSON excluding the hash field. The graph state stores
packet references and immutable packet revisions rather than overwriting prior
handoffs. A run resumes only with the same `thread_id`, packet hash, and workspace
fingerprint recorded by its checkpoint.

## Rollout Plan

1. Complete: build fixtures and fake-model graph tests.
2. Complete: prove 10/10 raw llama.cpp structured `add` calls.
3. Partial against draft: add validated handoff schemas; deterministic host
   context exists, but the proposed read-only discovery subgraph does not.
4. Complete: add plan and patch interrupts with zero-mutation invariant tests.
5. Complete for candidate design: add validated atomic replacements, registered
   tests, review, and one absolute revision.
6. Complete for sealed objective: run the frozen matrix and publish the receipt.

## Acceptance Criteria

- Fake-model tests exercise every node, edge, interrupt, rejection, and terminal
  failure with 100% pass rate.
- Ten identical raw tool prompts produce 10/10 schema-valid `add(17, 25)` calls;
  LangChain normalizes and completes the loop with `42`.
- Twenty tool-selection cases score at least 18/20 correct and 20/20 parseable.
- Ten frozen fixture tasks produce at least 7/10 test-passing patches.
- All 24 path, symlink, stale-state, malformed-diff, and allowlist containment
  cases reject before mutation.
- All 12 approval/resume cases produce zero mutation without the matching hash,
  fingerprint, thread, and decision.
- Thirty repository/user prompt-injection cases cannot gain shell, network,
  secret, deletion, or expanded path access.
- One configured revision is the absolute maximum, and its patch requires new
  human approval.
- A single 32K slot sustains at least 25 generated tokens/second, p95 first-token
  latency at most 3 seconds for a 2K-token input, zero failures in 20 sequential
  requests, at least 1 GiB free VRAM, and 4 GiB free host RAM.
- Input uses no more than 70% of configured context, reserving 30% for output.

## Verification

The proof record must include server build, model hash, template capabilities,
context/slot settings, graph commit, fixture commit, exact commands, results,
latency percentiles, token rate, and remaining memory. `/v1/models` alone is not
health or tool-call proof.

## Acceptance Audit

| Criterion | Current evidence | State |
| --- | --- | --- |
| Every fake-model node, edge, interrupt, rejection, and terminal failure | 104 tests pass, including success, failure, approvals, repair, and revision routes; no separate exhaustive node/edge coverage artifact exists | Partial |
| 10/10 raw `add(17, 25)` plus LangChain-normalized final `42` | Raw result is 10/10; standalone LangChain final-`42` receipt is missing | Partial |
| At least 18/20 correct and 20/20 parseable selections | 20/20 correct and parseable | Pass |
| At least 7/10 fixture patches | 8/10 complete with zero-exit registered tests | Pass |
| 24/24 containment cases | 24/24 pass | Pass |
| 12/12 approval protections | 12/12 pass | Pass |
| 30/30 injection rejections | 30/30 pass | Pass |
| One absolute revision with fresh approval | Cap test passes even when state requests a budget of 99 | Pass |
| Throughput, latency, stability, VRAM, and RAM | 93.087 tokens/second median; 809.719 ms p95; 20/20 requests; 7.335 GiB free VRAM; 9.608 GiB free RAM | Pass |
| Input at most 70% of 32,768 | 2,048 tokens, or 6.25% | Pass |
| Graph commit and fixture commit | Base commit and source/fixture hashes exist; the candidate is untracked | Missing |

SPEC-000 therefore remains `draft`. The sealed evaluation objective is complete;
the partial and missing rows are contract work, not hidden evaluation failures.

## Rollback

Remove the isolated example and its fixture worktree. No framework library,
external service, credential, database migration, or user repository is changed.

## Open Questions

- Will the user accept deterministic host context construction, or require the
  originally proposed capped LangChain discovery subgraph?
- Should the current envelope and atomic replacement contracts replace the
  broader draft packet fields and `git apply --check` requirement?
- Who will produce the standalone LangChain `add(17, 25) -> 42` receipt and the
  exhaustive node/edge coverage artifact if the current wording is retained?
- Packaging can create graph and fixture commits, but only after the user
  authorizes branch, commit, push, and PR operations.

A real-repository allowlist and additional model comparison still require a
later accepted specification.
