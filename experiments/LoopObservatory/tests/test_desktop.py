import json
import tkinter as tk

import pytest

from observatory import Observatory


@pytest.fixture
def view():
    root = tk.Tk()
    root.withdraw()
    app = Observatory(root)
    app.pack(fill="both", expand=True)
    yield root, app
    root.destroy()


def sample(tmp_path):
    path = tmp_path / "sample.jsonl"
    rows = [
        {"role": "plan", "response": {"content": "choose the exact file", "usage_metadata": {"output_tokens": 11}}},
        {"role": "patch", "attempt": 2, "response": {"content": "UNIQUE-PATCH-OUTPUT"}},
        {"role": "review", "error": "EXAMPLE-ERROR"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def test_load_select_draw_and_export(view, tmp_path):
    root, app = view
    app.load_file(sample(tmp_path))
    root.update_idletasks()
    assert len(app.events) == 3
    assert "3" in app.summary_var.get()
    assert isinstance(app.canvas, tk.Canvas)
    rectangles = [item for item in app.canvas.find_all() if app.canvas.type(item) == "rectangle"]
    assert len(rectangles) >= 3
    app.select_event(1)
    text = app.detail.get("1.0", "end")
    assert "UNIQUE-PATCH-OUTPUT" in text and "patch" in text.lower()
    app.select_event(-1)
    app.select_event(999)
    app.select_event(2)
    assert "EXAMPLE-ERROR" in app.detail.get("1.0", "end")
    output = tmp_path / "summary.json"
    app.export_summary(output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["summary"]["calls"] == 3
    assert saved["summary"]["repairs"] == 1
    assert saved["summary"]["errors"] == 1
    assert saved["warnings"] == []


def test_loading_second_file_replaces_first_and_shows_warnings(view, tmp_path):
    root, app = view
    app.load_file(sample(tmp_path))
    empty = tmp_path / "bad.jsonl"
    empty.write_text("not-json\n", encoding="utf-8")
    app.load_file(empty)
    root.update_idletasks()
    assert app.events == []
    assert len(app.warnings) == 1
    assert "warning" in app.summary_var.get().lower()
    app.select_event(0)
