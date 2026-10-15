"""Qwen-owned desktop interface. Implement Observatory and main per BRIEF.md."""
import json
import sys
import tkinter as tk
from pathlib import Path

from trace_reader import load_trace
from trace_metrics import summarize


class Observatory(tk.Frame):
    def __init__(self, root):
        super().__init__(root, bg="#1e1e1e")
        self.events = []
        self.warnings = []
        self.summary_var = tk.StringVar()
        self.canvas = tk.Canvas(self, height=110, bg="#2d2d2d")
        self.detail = tk.Text(self, bg="#2d2d2d", wrap="word")
        self.canvas.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.detail.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.canvas.columnconfigure(0, weight=1)
        self.detail.columnconfigure(0, weight=1)
        self.detail.rowconfigure(1, weight=1)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self._build_ui()

    def _build_ui(self):
        root = self.master
        root.title("Loop Observatory")
        root.geometry("1000x680")
        root.configure(bg="#1e1e1e")
        frame = tk.Frame(root, bg="#1e1e1e")
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        tk.Label(frame, text="Loop Observatory", font=("Helvetica", 16, "bold"), bg="#1e1e1e").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        tk.Label(frame, text="Recorded agent activity", font=("Helvetica", 10), bg="#1e1e1e").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        btn_frame = tk.Frame(frame, bg="#1e1e1e")
        btn_frame.grid(row=0, column=1, sticky="e", padx=10, pady=10)
        tk.Button(btn_frame, text="Open trace...", command=self._open_file, bg="#4a90e2", fg="white").pack(side="left", padx=5)
        tk.Button(btn_frame, text="Export summary", command=self._export_summary, bg="#5cb85c", fg="white").pack(side="left", padx=5)
        self.summary_var.set("calls: 0 | errors: 0 | failed_tests: 0 | repairs: 0 | output_tokens: 0")
        self.canvas.configure(xscrollcommand=self._scroll_horizontal)
        self._scroll_horizontal()
        self.detail.configure(yscrollcommand=self._scroll_vertical)
        self._scroll_vertical()
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        summary_label = tk.Label(frame, textvariable=self.summary_var, font=("Helvetica", 9), bg="#1e1e1e", fg="#cccccc")
        summary_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=5)

    def _scroll_horizontal(self, *args):
        self.canvas.xview_moveto(0)

    def _scroll_vertical(self, *args):
        self.detail.yview_moveto(0)

    def _on_canvas_configure(self, event):
        self.canvas.configure(scrollregion=(0, 0, event.width, event.height))

    def _on_canvas_click(self, event):
        if self.events:
            index = self.canvas.find_closest(event.x, event.y)[0]
            self.select_event(index)

    def _open_file(self):
        path = tk.filedialog.askopenfilename(title="Open trace", filetypes=[("JSONL", "*.jsonl")])
        if path:
            self.load_file(path)

    def _export_summary(self):
        path = tk.filedialog.asksaveasfilename(title="Export summary", filetypes=[("JSON", "*.json")])
        if path:
            self.export_summary(path)

    def load_file(self, path):
        try:
            events, warnings = load_trace(path)
        except FileNotFoundError:
            self.warnings = [f"File not found: {path}"]
            self.events = []
            self._update_ui()
            return
        self.events = events
        self.warnings = warnings
        self.detail.delete("1.0", tk.END)
        self._draw_cards()
        self._update_summary()
        self._scroll_vertical()

    def _draw_cards(self):
        self.canvas.delete("all")
        if not self.events:
            return
        colors = {"plan": "#5bc0de", "patch": "#f0ad4e", "review": "#5cb85c", "error": "#d9534f", "test-failed": "#d9534f", "unknown": "#999999"}
        for i, event in enumerate(self.events):
            x = 10 + i * 180
            y = 10
            width = 160
            height = 80
            rect_id = self.canvas.create_rectangle(x, y, x + width, y + height, fill=colors.get(event.get("role", "unknown")), outline="", tags=(f"rect_{i}", f"all"))
            text_id = self.canvas.create_text(x + width // 2, y + height // 2, text=event.get("role", "unknown"), fill="white", font=("Helvetica", 10, "bold"), tags=(f"text_{i}", "all"))

    def _update_summary(self):
        summary = summarize(self.events)
        self.summary_var.set(f"calls: {summary['calls']} | errors: {summary['errors']} | failed_tests: {summary['failed_tests']} | repairs: {summary['repairs']} | output_tokens: {summary['output_tokens']}")
        if self.warnings:
            self.summary_var.set(f"{self.summary_var.get()} | warnings: {len(self.warnings)}")

    def select_event(self, index):
        if not self.events or index < 0 or index >= len(self.events):
            return
        event = self.events[index]
        role = event.get("role", "unknown")
        status = event.get("status", "ok")
        output = event.get("output", "")
        colors = {"plan": "#5bc0de", "patch": "#f0ad4e", "review": "#5cb85c", "error": "#d9534f", "test-failed": "#d9534f", "unknown": "#999999"}
        outline_color = colors.get(role, "#999999")
        outline_width = 2
        for i in range(len(self.events)):
            rect_id = self.canvas.find_withtag(f"rect_{i}")
            if rect_id:
                self.canvas.itemconfigure(rect_id, outline="")
            text_id = self.canvas.find_withtag(f"text_{i}")
            if text_id:
                self.canvas.itemconfigure(text_id, fill="white")
        rect_id = self.canvas.find_withtag(f"rect_{index}")
        if rect_id:
            self.canvas.itemconfigure(rect_id, outline=outline_color, outline_width=outline_width)
        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, f"Role: {role}\nStatus: {status}\n\n{output}")
        self._scroll_vertical()

    def export_summary(self, path):
        summary = summarize(self.events)
        data = {"summary": summary, "warnings": self.warnings}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def main():
    root = tk.Tk()
    app = Observatory(root)
    app.pack(fill="both", expand=True)
    if len(sys.argv) > 1:
        app.load_file(sys.argv[1])
    else:
        bundled = Path(__file__).parent / "samples" / "demo.jsonl"
        if bundled.exists():
            app.load_file(bundled)
    root.mainloop()


if __name__ == "__main__":
    main()
