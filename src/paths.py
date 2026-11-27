from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "OCR Text In Vcam"
APP_VERSION = "1.0.0"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_bundle_dir() -> Path:
    """Read-only root containing bundled assets/models when frozen, or repo root in dev mode."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_user_data_dir() -> Path:
    """Writable app data root (%LOCALAPPDATA%\\OCR Text In Vcam when installed, repo root in dev)."""
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path(__file__).resolve().parent.parent


def get_default_log_dir() -> Path:
    """Default directory for timestamped OCR log files."""
    if is_frozen():
        return Path.home() / "Documents" / APP_NAME / "logs"
    return get_user_data_dir() / "logs"


def get_config_path() -> Path:
    return get_user_data_dir() / "config.json"


def get_bundled_models_dir() -> Path:
    return get_bundle_dir() / "models"


def get_writable_models_dir() -> Path:
    return get_user_data_dir() / "models"


def get_icon_path() -> Optional[Path]:
    for candidate in (
        get_bundle_dir() / "assets" / "app.ico",
        Path(__file__).resolve().parent.parent / "assets" / "app.ico",
    ):
        if candidate.exists():
            return candidate
    return None
