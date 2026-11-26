from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .capture import CaptureRegion, FrameDiffer, ScreenCaptureUnavailableError, ScreenCapturer
from .logger import LogRecord, OCRLogger
from .ocr_engine import EngineName, ScreenOCREngine


@dataclass
class ScanStats:
    scans: int = 0
    skipped: int = 0
    logged: int = 0
    last_elapsed_ms: float = 0.0


class ScreenOCRWorker:
    """Background polling worker: capture screen region -> frame-diff -> OCR -> timestamped log."""

    def __init__(
        self,
        region: CaptureRegion,
        logger: OCRLogger,
        engine: Optional[ScreenOCREngine] = None,
        engine_name: EngineName = "vietocr",
        interval_sec: float = 0.5,
        min_confidence: float = 0.5,
        diff_threshold: float = 1.2,
        on_record: Optional[Callable[[LogRecord], None]] = None,
        on_status: Optional[Callable[[str, ScanStats], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self.region = region
        self.logger = logger
        self.engine = engine
        self.engine_name: EngineName = engine_name
        self.interval_sec = max(0.05, float(interval_sec))
        self.min_confidence = float(min_confidence)
        self.diff_threshold = float(diff_threshold)

        self.on_record = on_record
        self.on_status = on_status
        self.on_error = on_error

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.stats = ScanStats()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self.stats = ScanStats()
        self._thread = threading.Thread(target=self._run, name="ScreenOCRWorker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_once(self) -> Optional[LogRecord]:
        """Run a single synchronous capture -> OCR -> log pass."""
        capturer = ScreenCapturer()
        try:
            engine = self._ensure_engine()
            bgr = capturer.grab_bgr(self.region)
            res = engine.read(bgr)
            self.stats.scans += 1
            self.stats.last_elapsed_ms = res.elapsed_ms
            record = self.logger.log(
                lines=res.lines,
                avg_confidence=res.avg_confidence,
                elapsed_ms=res.elapsed_ms,
                region=self.region.to_dict(),
            )
            if record is not None:
                self.stats.logged += 1
                if self.on_record:
                    self.on_record(record)
            return record
        finally:
            capturer.close_thread_handle()

    def _ensure_engine(self) -> ScreenOCREngine:
        if self.engine is None:
            self.engine = ScreenOCREngine(
                engine=self.engine_name,
                min_confidence=self.min_confidence,
                on_status=lambda msg: self.on_status(msg, self.stats) if self.on_status else None,
            )
        return self.engine

    def _run(self) -> None:
        capturer = ScreenCapturer()
        differ = FrameDiffer(threshold=self.diff_threshold)
        try:
            engine = self._ensure_engine()
            if self.on_status:
                self.on_status(f"Đang theo dõi {self.region.label()}", self.stats)

            paused_notice_shown = False
            while not self._stop_event.is_set():
                loop_start = time.perf_counter()
                try:
                    bgr = capturer.grab_bgr(self.region)
                    paused_notice_shown = False
                    if not differ.has_changed(bgr):
                        self.stats.skipped += 1
                    else:
                        res = engine.read(bgr)
                        self.stats.scans += 1
                        self.stats.last_elapsed_ms = res.elapsed_ms
                        record = self.logger.log(
                            lines=res.lines,
                            avg_confidence=res.avg_confidence,
                            elapsed_ms=res.elapsed_ms,
                            region=self.region.to_dict(),
                        )
                        if record is not None:
                            self.stats.logged += 1
                            if self.on_record:
                                self.on_record(record)
                        if self.on_status:
                            self.on_status(
                                f"Đang chạy | OCR: {res.elapsed_ms:.0f}ms | Đã ghi: {self.stats.logged}",
                                self.stats,
                            )
                except ScreenCaptureUnavailableError:
                    if not paused_notice_shown and self.on_status:
                        self.on_status("Tạm chờ màn hình khả dụng (đang khóa/UAC)...", self.stats)
                        paused_notice_shown = True
                except Exception as exc:
                    if self.on_error:
                        self.on_error(exc)
                    else:
                        raise

                spent = time.perf_counter() - loop_start
                sleep_for = self.interval_sec - spent
                if sleep_for > 0:
                    self._stop_event.wait(timeout=sleep_for)
        except Exception as exc:
            if self.on_error:
                self.on_error(exc)
        finally:
            capturer.close_thread_handle()
            if self.on_status:
                self.on_status("Đã dừng", self.stats)
