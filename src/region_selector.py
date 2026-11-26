from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Optional

from .capture import CaptureRegion, enable_dpi_awareness, get_monitor_region


def load_saved_region(config_path: Path) -> Optional[CaptureRegion]:
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        region = data.get("region")
        if isinstance(region, dict):
            return CaptureRegion.from_dict(region)
    except Exception:
        return None
    return None


def save_region(config_path: Path, region: CaptureRegion) -> None:
    data: dict = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
        except Exception:
            data = {}
    data["region"] = region.to_dict()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def select_region_interactive(parent: Optional[tk.Misc] = None) -> Optional[CaptureRegion]:
    """
    Open a translucent overlay spanning the entire virtual desktop so the user can drag a box.
    Press Esc or right-click to cancel. Press F to pick the primary monitor full screen.
    """
    enable_dpi_awareness()
    virtual = get_monitor_region(0)

    owns_root = parent is None
    win = tk.Tk() if owns_root else tk.Toplevel(parent)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.30)
    win.configure(bg="#0b0f17", cursor="crosshair")
    win.geometry(f"{virtual.width}x{virtual.height}{virtual.left:+d}{virtual.top:+d}")

    canvas = tk.Canvas(
        win,
        bg="#0b0f17",
        highlightthickness=0,
        cursor="crosshair",
    )
    canvas.pack(fill=tk.BOTH, expand=True)

    # Instruction banner centered on primary monitor
    primary = get_monitor_region(1)
    banner_x = (primary.left - virtual.left) + primary.width // 2
    banner_y = (primary.top - virtual.top) + 48
    canvas.create_rectangle(
        banner_x - 310,
        banner_y - 24,
        banner_x + 310,
        banner_y + 24,
        fill="#111827",
        outline="#38bdf8",
        width=2,
    )
    canvas.create_text(
        banner_x,
        banner_y,
        text="Kéo chuột để chọn vùng OCR  |  F: Toàn màn hình  |  Esc: Hủy",
        fill="#f8fafc",
        font=("Segoe UI", 12, "bold"),
    )

    state: dict[str, object] = {
        "start_x": None,
        "start_y": None,
        "rect_id": None,
        "label_id": None,
        "result": None,
    }

    def close_with(region: Optional[CaptureRegion]) -> None:
        state["result"] = region
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    def on_press(event: tk.Event) -> None:
        state["start_x"] = event.x
        state["start_y"] = event.y
        if state["rect_id"] is not None:
            canvas.delete(state["rect_id"])
        if state["label_id"] is not None:
            canvas.delete(state["label_id"])
        state["rect_id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#22d3ee",
            width=3,
            fill="#0284c7",
            stipple="gray25",
        )
        state["label_id"] = canvas.create_text(
            event.x + 8,
            max(16, event.y - 16),
            anchor="w",
            fill="#f8fafc",
            font=("Consolas", 11, "bold"),
            text="",
        )

    def on_drag(event: tk.Event) -> None:
        sx = state["start_x"]
        sy = state["start_y"]
        if sx is None or sy is None:
            return
        x1, y1 = min(int(sx), event.x), min(int(sy), event.y)
        x2, y2 = max(int(sx), event.x), max(int(sy), event.y)
        canvas.coords(state["rect_id"], x1, y1, x2, y2)
        canvas.coords(state["label_id"], x1 + 6, max(16, y1 - 16))
        canvas.itemconfigure(state["label_id"], text=f"{x2 - x1} x {y2 - y1}")

    def on_release(event: tk.Event) -> None:
        sx = state["start_x"]
        sy = state["start_y"]
        if sx is None or sy is None:
            return
        x1, y1 = min(int(sx), event.x), min(int(sy), event.y)
        x2, y2 = max(int(sx), event.x), max(int(sy), event.y)
        w = x2 - x1
        h = y2 - y1
        if w < 12 or h < 12:
            # Too small, ignore accidental click
            return
        region = CaptureRegion(
            left=virtual.left + x1,
            top=virtual.top + y1,
            width=w,
            height=h,
        )
        close_with(region)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Button-3>", lambda _e: close_with(None))
    win.bind("<Escape>", lambda _e: close_with(None))
    win.bind("f", lambda _e: close_with(primary))
    win.bind("F", lambda _e: close_with(primary))

    win.focus_force()
    win.grab_set()
    if owns_root:
        win.mainloop()
    else:
        parent.wait_window(win)

    return state["result"]  # type: ignore[return-value]
