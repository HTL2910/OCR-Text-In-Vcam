from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .capture import CaptureRegion, enable_dpi_awareness, get_monitor_region
from .logger import LogRecord, OCRLogger
from .ocr_engine import EngineName, ScreenOCREngine
from .region_selector import load_saved_region, save_region, select_region_interactive
from .worker import ScanStats, ScreenOCRWorker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"


class OCRAppGUI:
    def __init__(self) -> None:
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("OCR Text In Vcam — Screen Logger")
        self.root.geometry("760x540")
        self.root.minsize(640, 440)
        self.root.configure(bg="#0f172a")

        self.region: Optional[CaptureRegion] = load_saved_region(DEFAULT_CONFIG)
        self.worker: Optional[ScreenOCRWorker] = None
        self.cached_engines: dict[EngineName, ScreenOCREngine] = {}
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.engine_var = tk.StringVar(value="vietocr")
        self.interval_var = tk.StringVar(value="0.5")
        self.min_conf_var = tk.StringVar(value="0.5")
        self.dedup_var = tk.BooleanVar(value=True)
        self.jsonl_var = tk.BooleanVar(value=False)
        self.topmost_var = tk.BooleanVar(value=False)
        self.log_path_var = tk.StringVar(value=str(DEFAULT_LOG_DIR))
        self.region_var = tk.StringVar(
            value=self.region.label() if self.region else "Chưa chọn vùng (mặc định toàn màn hình)"
        )
        self.status_var = tk.StringVar(value="Sẵn sàng")

        self._setup_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_queue)

    def _setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#0f172a")
        style.configure("Card.TFrame", background="#1e293b")
        style.configure("TLabel", background="#0f172a", foreground="#e2e8f0", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#1e293b", foreground="#e2e8f0", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#1e293b", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("TCheckbutton", background="#1e293b", foreground="#e2e8f0", font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", "#1e293b")])
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 6))
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 5))

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        # Top control card
        top = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        top.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(top, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row1, text="Vùng quét:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Label(row1, textvariable=self.region_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 12))
        ttk.Button(row1, text="Toàn màn hình", command=self._pick_fullscreen).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(row1, text="Chọn vùng (Kéo chuột)", command=self._pick_region).pack(side=tk.RIGHT)

        row2 = ttk.Frame(top, style="Card.TFrame")
        row2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row2, text="Engine:", style="Card.TLabel").pack(side=tk.LEFT)
        engine_box = ttk.Combobox(
            row2,
            textvariable=self.engine_var,
            values=["vietocr", "rapidocr"],
            state="readonly",
            width=12,
        )
        engine_box.pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row2, text="Chu kỳ (s):", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.interval_var, width=6).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row2, text="Min Conf:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.min_conf_var, width=6).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Checkbutton(row2, text="Lọc trùng", variable=self.dedup_var).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(row2, text="JSONL", variable=self.jsonl_var).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(row2, text="Luôn nổi", variable=self.topmost_var, command=self._toggle_topmost).pack(
            side=tk.LEFT
        )

        row3 = ttk.Frame(top, style="Card.TFrame")
        row3.pack(fill=tk.X)
        ttk.Label(row3, text="Thư mục log:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.log_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(row3, text="Đổi...", command=self._choose_log_dir).pack(side=tk.LEFT)

        # Action bar
        actions = ttk.Frame(self.root)
        actions.pack(fill=tk.X, padx=12, pady=(2, 6))

        self.start_btn = ttk.Button(actions, text="▶ Bắt đầu đọc", style="Accent.TButton", command=self._toggle_start)
        self.start_btn.pack(side=tk.LEFT)

        ttk.Button(actions, text="Quét 1 lần", command=self._scan_once).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Mở file log", command=self._open_current_log).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Mở thư mục", command=self._open_log_folder).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Xóa hiển thị", command=self._clear_log_view).pack(side=tk.RIGHT)

        # Live log text box
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        self.log_text = tk.Text(
            log_frame,
            bg="#020617",
            fg="#e2e8f0",
            insertbackground="#38bdf8",
            font=("Consolas", 10),
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Status bar
        status_bar = ttk.Frame(self.root, style="Card.TFrame", padding=(12, 6))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT)

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    def _pick_region(self) -> None:
        was_running = self.worker is not None and self.worker.is_running
        if was_running:
            self._stop_worker()
        self.root.withdraw()
        self.root.update_idletasks()
        try:
            chosen = select_region_interactive(parent=self.root)
        finally:
            self.root.deiconify()
            self.root.lift()
        if chosen is not None:
            self.region = chosen
            save_region(DEFAULT_CONFIG, chosen)
            self.region_var.set(chosen.label())
            self.status_var.set(f"Đã chọn vùng {chosen.label()}")
        if was_running:
            self._start_worker()

    def _pick_fullscreen(self) -> None:
        self.region = get_monitor_region(1)
        save_region(DEFAULT_CONFIG, self.region)
        self.region_var.set(f"Toàn màn hình {self.region.label()}")
        self.status_var.set("Đã chuyển sang toàn màn hình chính")

    def _choose_log_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.log_path_var.get() or str(DEFAULT_LOG_DIR))
        if chosen:
            self.log_path_var.set(chosen)

    def _build_logger(self) -> OCRLogger:
        log_dir = Path(self.log_path_var.get().strip() or DEFAULT_LOG_DIR)
        jsonl_path = (log_dir / "ocr_events.jsonl") if self.jsonl_var.get() else None
        return OCRLogger(
            log_dir=log_dir,
            jsonl_file=jsonl_path,
            dedup=bool(self.dedup_var.get()),
        )

    def _parse_params(self) -> tuple[float, float, EngineName]:
        try:
            interval = max(0.1, float(self.interval_var.get().strip()))
        except ValueError:
            interval = 0.5
            self.interval_var.set("0.5")
        try:
            min_conf = max(0.0, min(1.0, float(self.min_conf_var.get().strip())))
        except ValueError:
            min_conf = 0.5
            self.min_conf_var.set("0.5")
        eng: EngineName = "rapidocr" if self.engine_var.get() == "rapidocr" else "vietocr"
        return interval, min_conf, eng

    def _toggle_start(self) -> None:
        if self.worker is not None and self.worker.is_running:
            self._stop_worker()
        else:
            self._start_worker()

    def _start_worker(self) -> None:
        if self.region is None:
            self.region = get_monitor_region(1)
            self.region_var.set(f"Toàn màn hình {self.region.label()}")

        interval, min_conf, eng_name = self._parse_params()
        logger = self._build_logger()
        cached = self.cached_engines.get(eng_name)
        if cached is not None:
            cached.min_confidence = min_conf

        self.worker = ScreenOCRWorker(
            region=self.region,
            logger=logger,
            engine=cached,
            engine_name=eng_name,
            interval_sec=interval,
            min_confidence=min_conf,
            on_record=lambda rec: self.ui_queue.put(("record", rec)),
            on_status=lambda msg, st: self.ui_queue.put(("status", (msg, st))),
            on_error=lambda exc: self.ui_queue.put(("error", exc)),
        )
        self.start_btn.configure(text="■ Dừng đọc")
        self.status_var.set("Đang khởi động engine OCR...")
        self.worker.start()

    def _stop_worker(self) -> None:
        if self.worker is not None:
            if self.worker.engine is not None:
                self.cached_engines[self.worker.engine_name] = self.worker.engine
            self.worker.stop()
            self.worker = None
        self.start_btn.configure(text="▶ Bắt đầu đọc")
        self.status_var.set("Đã dừng")

    def _scan_once(self) -> None:
        if self.worker is not None and self.worker.is_running:
            messagebox.showinfo("Đang chạy", "Vui lòng dừng chế độ theo dõi liên tục trước khi quét 1 lần.")
            return
        if self.region is None:
            self.region = get_monitor_region(1)
            self.region_var.set(f"Toàn màn hình {self.region.label()}")

        interval, min_conf, eng_name = self._parse_params()
        logger = self._build_logger()
        logger.dedup = False
        cached = self.cached_engines.get(eng_name)
        if cached is not None:
            cached.min_confidence = min_conf

        worker = ScreenOCRWorker(
            region=self.region,
            logger=logger,
            engine=cached,
            engine_name=eng_name,
            interval_sec=interval,
            min_confidence=min_conf,
            on_record=lambda rec: self.ui_queue.put(("record", rec)),
            on_status=lambda msg, st: self.ui_queue.put(("status", (msg, st))),
            on_error=lambda exc: self.ui_queue.put(("error", exc)),
        )
        self.status_var.set("Đang quét 1 khung hình...")

        def task() -> None:
            try:
                rec = worker.run_once()
                if worker.engine is not None:
                    self.cached_engines[eng_name] = worker.engine
                if rec is None:
                    self.ui_queue.put(("status", ("Không thấy chữ trong vùng chọn", ScanStats())))
                else:
                    self.ui_queue.put(("status", (f"Quét xong ({rec.elapsed_ms:.0f}ms)", worker.stats)))
            except Exception as exc:
                self.ui_queue.put(("error", exc))

        import threading

        threading.Thread(target=task, daemon=True).start()

    def _append_text(self, line: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log_view(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_current_log(self) -> None:
        logger = self._build_logger()
        path = logger.current_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _open_log_folder(self) -> None:
        log_dir = Path(self.log_path_var.get().strip() or DEFAULT_LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(log_dir))
        else:
            subprocess.Popen(["xdg-open", str(log_dir)])

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "record":
                    rec: LogRecord = payload  # type: ignore[assignment]
                    self._append_text(rec.format_line())
                elif kind == "status":
                    msg, _stats = payload  # type: ignore[misc]
                    self.status_var.set(str(msg))
                    if self.worker is not None and self.worker.engine is not None:
                        self.cached_engines[self.worker.engine_name] = self.worker.engine
                elif kind == "error":
                    self._append_text(f"[LỖI] {payload}")
                    self.status_var.set(f"Lỗi: {payload}")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _on_close(self) -> None:
        self._stop_worker()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    OCRAppGUI().run()


if __name__ == "__main__":
    launch_gui()
