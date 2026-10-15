from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from graph_engineer.context import resolve_inside
from graph_engineer.packets import FileReplacement, TestReceipt


@dataclass(frozen=True)
class RegisteredCommand:
    argv: tuple[str, ...]
    timeout_seconds: int = 60


COMMANDS = {
    "pytest": RegisteredCommand((sys.executable, "-m", "pytest", "-q"), 60),
}


def validate_replacements(
    root: Path, replacements: tuple[FileReplacement, ...], allowed_write_paths: set[str]
) -> None:
    for replacement in replacements:
        if replacement.path not in allowed_write_paths:
            raise ValueError(f"path is not writable: {replacement.path}")
        path = resolve_inside(root, replacement.path)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"replacement target must be a regular file: {replacement.path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != replacement.expected_sha256:
            raise ValueError(f"stale replacement target: {replacement.path}")


def apply_replacements(root: Path, replacements: tuple[FileReplacement, ...]) -> None:
    for replacement in replacements:
        target = resolve_inside(root, replacement.path)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=target.parent, delete=False
        ) as handle:
            handle.write(replacement.content)
            temporary = Path(handle.name)
        os.replace(temporary, target)


def run_registered_test(root: Path, command_id: str, *, output_limit: int = 12000) -> TestReceipt:
    command = COMMANDS.get(command_id)
    if command is None:
        raise ValueError(f"unregistered command: {command_id}")
    started = time.perf_counter()
    completed = subprocess.run(
        command.argv,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=command.timeout_seconds,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    return TestReceipt(
        command_id=command_id,
        argv=command.argv,
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        stdout=completed.stdout[-output_limit:],
        stderr=completed.stderr[-output_limit:],
    )
