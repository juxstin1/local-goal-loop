from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_tasks() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "tasks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def materialize_task(task: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "solution.py").write_text(task["source"], encoding="utf-8")
    (root / "test_solution.py").write_text(task["tests"], encoding="utf-8")
    (root / "TASK.md").write_text(f"# Task\n\n{task['objective']}\n", encoding="utf-8")
    return root
