from __future__ import annotations

import hashlib
from pathlib import Path

from graph_engineer.packets import ContextPacket, EvidenceRef, canonical_hash

EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".yaml", ".yml"}


def resolve_inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes repository: {relative}")
    return candidate


def repository_fingerprint(root: Path, *, exclude_paths: tuple[str, ...] = ()) -> str:
    records: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude_paths:
            continue
        records.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return canonical_hash(records)


def build_context(root: Path, *, budget_chars: int) -> ContextPacket:
    root = root.resolve()
    evidence: list[EvidenceRef] = []
    used = 0
    truncated = False
    candidates = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not any(part in EXCLUDED_PARTS for part in path.parts)
    ]
    for index, path in enumerate(candidates, start=1):
        raw = path.read_text(encoding="utf-8", errors="replace")
        remaining = budget_chars - used
        if remaining <= 0:
            truncated = True
            break
        excerpt = raw[:remaining]
        if len(excerpt) < len(raw):
            truncated = True
        lines = excerpt.splitlines()
        if not lines:
            continue
        evidence.append(
            EvidenceRef(
                id=f"EVID-{index:03d}",
                path=path.relative_to(root).as_posix(),
                start_line=1,
                end_line=len(lines),
                excerpt=excerpt,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
        used += len(excerpt)
    return ContextPacket(
        repository_fingerprint=repository_fingerprint(root),
        evidence=tuple(evidence),
        gaps=("context truncated to configured character budget",) if truncated else (),
        budget_chars=budget_chars,
        used_chars=used,
        truncated=truncated,
    )
