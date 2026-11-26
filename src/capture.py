from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass
from typing import Optional

import mss
from mss.exception import ScreenShotError
import numpy as np
from PIL import ImageGrab

_dpi_initialized = False


def enable_dpi_awareness() -> None:
    """Switch Windows process to Per-Monitor DPI Aware v2 so Tkinter and mss coordinates match 1:1."""
    global _dpi_initialized
    if _dpi_initialized or sys.platform != "win32":
        return
    _dpi_initialized = True
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int

    def to_mss(self) -> dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }

    def to_dict(self) -> dict[str, int]:
        return self.to_mss()

    @classmethod
    def from_dict(cls, data: dict) -> "CaptureRegion":
        return cls(
            left=int(data["left"]),
            top=int(data["top"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )

    @classmethod
    def parse(cls, spec: str) -> "CaptureRegion":
        parts = [int(p.strip()) for p in spec.split(",")]
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise ValueError("Region must be 'left,top,width,height' with width>0 and height>0")
        return cls(parts[0], parts[1], parts[2], parts[3])

    def label(self) -> str:
        return f"({self.left}, {self.top}) {self.width}x{self.height}"


def get_monitor_region(monitor_index: int = 1) -> CaptureRegion:
    """Return CaptureRegion for monitor_index (0 = all monitors combined, 1 = primary, 2+ = secondary)."""
    enable_dpi_awareness()
    with mss.MSS() as sct:
        if monitor_index < 0 or monitor_index >= len(sct.monitors):
            raise ValueError(
                f"Monitor index {monitor_index} out of range (available: 0..{len(sct.monitors) - 1})"
            )
        m = sct.monitors[monitor_index]
        return CaptureRegion(m["left"], m["top"], m["width"], m["height"])


def list_monitors() -> list[CaptureRegion]:
    enable_dpi_awareness()
    with mss.MSS() as sct:
        return [
            CaptureRegion(m["left"], m["top"], m["width"], m["height"])
            for m in sct.monitors
        ]


class ScreenCaptureUnavailableError(RuntimeError):
    """Raised when the desktop cannot be captured (e.g. Windows lock screen or UAC prompt)."""


class ScreenCapturer:
    """Thread-safe mss screen capturer returning BGR uint8 numpy arrays, with ImageGrab fallback."""

    def __init__(self) -> None:
        enable_dpi_awareness()
        self._local = threading.local()

    def _get_sct(self) -> mss.base.MSSBase:
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.MSS()
            self._local.sct = sct
        return sct

    def grab_bgr(self, region: CaptureRegion) -> np.ndarray:
        """Capture region as contiguous BGR uint8 array (H, W, 3)."""
        try:
            sct = self._get_sct()
            raw = sct.grab(region.to_mss())
            bgra = np.frombuffer(raw.bgra, dtype=np.uint8).reshape((raw.height, raw.width, 4))
            return np.ascontiguousarray(bgra[:, :, :3])
        except ScreenShotError as exc:
            # Fallback to Pillow ImageGrab; if still blocked (lock screen / UAC), raise clear error
            bbox = (region.left, region.top, region.left + region.width, region.top + region.height)
            try:
                pil_img = ImageGrab.grab(bbox=bbox, all_screens=True)
                rgb = np.asarray(pil_img.convert("RGB"), dtype=np.uint8)
                return np.ascontiguousarray(rgb[:, :, ::-1])
            except Exception:
                raise ScreenCaptureUnavailableError(
                    "Không chụp được màn hình (màn hình đang khóa, UAC hoặc phiên không tương tác)."
                ) from exc

    def close_thread_handle(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            finally:
                self._local.sct = None


class FrameDiffer:
    """Skips OCR when captured pixels haven't meaningfully changed."""

    def __init__(self, threshold: float = 1.2) -> None:
        self.threshold = float(threshold)
        self._last_thumb: Optional[np.ndarray] = None

    def reset(self) -> None:
        self._last_thumb = None

    def has_changed(self, bgr: np.ndarray) -> bool:
        if self.threshold <= 0:
            return True
        # Subsample to ~160px on longest side for sub-millisecond diffing
        h, w = bgr.shape[:2]
        step_y = max(1, h // 160)
        step_x = max(1, w // 160)
        # Fast integer luma approximation on strided view
        sample = bgr[::step_y, ::step_x]
        gray = (
            sample[:, :, 0].astype(np.int16)
            + (sample[:, :, 1].astype(np.int16) << 1)
            + sample[:, :, 2].astype(np.int16)
        ) >> 2

        if self._last_thumb is None or self._last_thumb.shape != gray.shape:
            self._last_thumb = gray
            return True

        diff = float(np.mean(np.abs(gray - self._last_thumb)))
        if diff >= self.threshold:
            self._last_thumb = gray
            return True
        return False
