"""Additional checks after initial DESKTOP passed but omitted UI requirements."""
import json
import tkinter as tk
import pytest
from observatory import Observatory

@pytest.fixture
def ui(tmp_path):
    root = tk.Tk()
    root.withdraw()
    try:
        app = Observatory(root)
        app.pack(fill="both", expand=True)
        rows = [{"role":role,"response":{"content":f"OUTPUT-{i}"}} for i,role in enumerate(["plan","patch","review"])]
        path = tmp_path / "trace.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows),encoding="utf-8")
        app.load_file(path)
        root.update_idletasks()
        yield root,app
    finally:
        root.destroy()

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

def test_summary_has_a_visible_widget(ui):
    root,app = ui
    widgets = list(descendants(root))
    assert any("textvariable" in w.keys() and str(w.cget("textvariable"))==str(app.summary_var) and w.winfo_manager() for w in widgets)

def test_horizontal_scrolling_is_wired(ui):
    root,app = ui
    bars = [w for w in descendants(app) if isinstance(w,tk.Scrollbar) and str(w.cget("orient"))=="horizontal"]
    assert bars and any(bar.cget("command") for bar in bars)
    assert app.canvas.cget("xscrollcommand")
    assert app.canvas.cget("scrollregion")

def test_each_card_is_clickable_and_roles_have_distinct_colors(ui):
    root,app = ui
    canvas = app.canvas
    rectangles = [item for item in canvas.find_all() if canvas.type(item)=="rectangle"]
    assert len(set(canvas.itemcget(r,"fill") for r in rectangles)) >= 3
    for rect in rectangles:
        targets = [rect,*canvas.gettags(rect),"all"]
        assert canvas.bind("<Button-1>") or any(canvas.tag_bind(tag,"<Button-1>") for tag in targets)

def test_empty_trace_clears_old_details(ui,tmp_path):
    root,app = ui
    app.select_event(1)
    assert "OUTPUT-1" in app.detail.get("1.0","end")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("",encoding="utf-8")
    app.load_file(empty)
    assert "OUTPUT-1" not in app.detail.get("1.0","end")

def test_interface_uses_same_parser_contract(ui,tmp_path):
    from trace_reader import load_trace
    root,app = ui
    path = tmp_path / "unusual.jsonl"
    path.write_text(json.dumps({"role": ["bad"], "attempt": "bad", "response": []}),encoding="utf-8")
    expected,warnings = load_trace(path)
    app.load_file(path)
    assert app.events == expected and app.warnings == warnings

def test_selection_preserves_role_colors_and_all_cards_are_reachable(ui,tmp_path):
    root,app = ui
    path = tmp_path / "long.jsonl"
    path.write_text("\n".join(json.dumps({"role":r}) for r in ["plan","patch","review"]*10),encoding="utf-8")
    app.load_file(path)
    canvas = app.canvas
    rects = [i for i in canvas.find_all() if canvas.type(i)=="rectangle"]
    colors = [canvas.itemcget(i,"fill") for i in rects]
    app.select_event(1)
    assert [canvas.itemcget(i,"fill") for i in rects] == colors
    bounds = [float(v) for v in str(canvas.cget("scrollregion")).split()]
    assert bounds[2] >= max(canvas.coords(i)[2] for i in rects)
