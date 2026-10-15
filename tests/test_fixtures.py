from __future__ import annotations

from pathlib import Path

import pytest

from graph_engineer.execution import run_registered_test
from graph_engineer.fixture import load_tasks, materialize_task


@pytest.mark.parametrize("task", load_tasks(), ids=lambda task: task["id"])
def test_frozen_fixture_starts_red_and_expected_source_turns_green(
    tmp_path: Path, task: dict[str, str]
) -> None:
    root = materialize_task(task, tmp_path / task["id"])

    before = run_registered_test(root, "pytest")
    (root / "solution.py").write_text(task["expected_source"], encoding="utf-8")
    after = run_registered_test(root, "pytest")

    assert before.exit_code != 0
    assert after.exit_code == 0
