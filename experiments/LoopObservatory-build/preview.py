"""Host-owned visible interaction check and screenshot capture."""
import json
from pathlib import Path
import sys
import tkinter as tk
from PIL import ImageGrab

base = Path(__file__).resolve().parent
project = base.parent / "LoopObservatory"
sys.path.insert(0,str(project))
from observatory import Observatory

root = tk.Tk()
root.title("Loop Observatory — local Qwen build")
root.geometry("1000x680+80+80")
app = Observatory(root)
app.pack(fill="both",expand=True)
errors = []
root.report_callback_exception = lambda kind,value,tb: errors.append(f"{kind.__name__}: {value}")
app.load_file(project / "samples/demo.jsonl")
results = {}
def check():
    try:
        canvas = app.canvas
        rects = [item for item in canvas.find_all() if canvas.type(item)=="rectangle"]
        x1,y1,x2,y2 = canvas.coords(rects[1])
        x = int((x1+x2)/2-canvas.canvasx(0))
        y = int((y1+y2)/2-canvas.canvasy(0))
        canvas.event_generate("<Motion>",x=x,y=y)
        canvas.event_generate("<ButtonPress-1>",x=x,y=y)
        canvas.event_generate("<ButtonRelease-1>",x=x,y=y)
        root.update()
        detail = app.detail.get("1.0","end")
        results["click_selected_patch"] = "patch" in detail.lower() and "def " in detail
        before = canvas.xview()
        canvas.xview_moveto(1)
        root.update()
        results["horizontal_scroll_moves"] = before != canvas.xview()
        canvas.xview_moveto(0)
        app.export_summary(base / "preview-summary.json")
        results["exported_calls"] = json.loads((base / "preview-summary.json").read_text())["summary"]["calls"]
        root.update()
        image = ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height()))
        image.save(base / "preview.png")
        results["callback_errors"] = errors
    except Exception as error:
        results["error"] = f"{type(error).__name__}: {error}"
    finally:
        (base / "preview-check.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        print(json.dumps(results),flush=True)
        if "--keep-open" not in sys.argv:
            root.destroy()
root.after(1200,check)
root.mainloop()
