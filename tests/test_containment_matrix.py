from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from graph_engineer.context import resolve_inside
from graph_engineer.execution import validate_replacements
from graph_engineer.packets import FileReplacement

ESCAPE_PATHS = [
    "../outside.py",
    "../../outside.py",
    "sub/../../../outside.py",
    "C:/Windows/outside.py",
    "C:\\Windows\\outside.py",
    "/absolute/outside.py",
    "..\\outside.py",
    "sub\\..\\..\\outside.py",
    "nested/../../../../outside.py",
    "./../../outside.py",
]

OUT_OF_ALLOWLIST_PATHS = [
    "TASK.md",
    "test_solution.py",
    ".env",
    "config.toml",
    "nested.py",
    "secret.txt",
]

STALE_DIGESTS = ["0" * 64, "1" * 64, hashlib.sha256(b"stale").hexdigest()]

MALFORMED_REPLACEMENTS = [
    {"path": "solution.py", "expected_sha256": "short", "content": "x = 1\n"},
    {"path": "solution.py", "expected_sha256": "A" * 64, "content": "x = 1\n"},
    {"path": "solution.py", "expected_sha256": "0" * 64, "content": ""},
]


@pytest.mark.parametrize("relative", ESCAPE_PATHS, ids=lambda value: f"escape-{value}")
def test_containment_rejects_path_escape(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        resolve_inside(tmp_path, relative)


@pytest.mark.parametrize("relative", OUT_OF_ALLOWLIST_PATHS, ids=lambda value: f"allowlist-{value}")
def test_containment_rejects_out_of_allowlist_path(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("protected\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    replacement = FileReplacement(path=relative, expected_sha256=digest, content="changed\n")

    with pytest.raises(ValueError, match="path is not writable"):
        validate_replacements(tmp_path, (replacement,), {"solution.py"})


@pytest.mark.parametrize("digest", STALE_DIGESTS, ids=("stale-zero", "stale-one", "stale-hash"))
def test_containment_rejects_stale_target(tmp_path: Path, digest: str) -> None:
    target = tmp_path / "solution.py"
    target.write_text("original\n", encoding="utf-8")
    replacement = FileReplacement(path="solution.py", expected_sha256=digest, content="changed\n")

    with pytest.raises(ValueError, match="stale replacement target"):
        validate_replacements(tmp_path, (replacement,), {"solution.py"})


@pytest.mark.parametrize("relative", ("missing.py", "directory"), ids=("missing", "directory"))
def test_containment_rejects_non_regular_target(tmp_path: Path, relative: str) -> None:
    if relative == "directory":
        (tmp_path / relative).mkdir()
    replacement = FileReplacement(path=relative, expected_sha256="0" * 64, content="changed\n")

    with pytest.raises(ValueError, match="regular file"):
        validate_replacements(tmp_path, (replacement,), {relative})


@pytest.mark.parametrize(
    "payload", MALFORMED_REPLACEMENTS, ids=("short-sha", "uppercase-sha", "empty-content")
)
def test_containment_rejects_malformed_replacement(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        FileReplacement.model_validate(payload)
