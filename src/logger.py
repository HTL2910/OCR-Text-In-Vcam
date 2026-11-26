from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True)
class LogRecord:
    timestamp: str
    text: str
    lines: list[str]
    avg_confidence: float
    elapsed_ms: float
    region: Optional[dict[str, int]] = None
    log_path: str = ""

    def format_line(self, multiline: bool = False, separator: str = " | ") -> str:
        if multiline and len(self.lines) > 1:
            body = "\n".join(f"    {ln}" for ln in self.lines)
            return f"[{self.timestamp}]\n{body}"
        joined = separator.join(self.lines) if self.lines else self.text
        return f"[{self.timestamp}] {joined}"


class OCRLogger:
    """Thread-safe timestamped file logger with exact/fuzzy deduplication and daily rotation."""

    def __init__(
        self,
        log_dir: Path,
        fixed_log_file: Optional[Path] = None,
        jsonl_file: Optional[Path] = None,
        dedup: bool = True,
        similarity_threshold: float = 1.0,
        repeat_after_sec: float = 0.0,
        multiline: bool = False,
        separator: str = " | ",
    ) -> None:
        self.log_dir = Path(log_dir)
        self.fixed_log_file = Path(fixed_log_file) if fixed_log_file else None
        self.jsonl_file = Path(jsonl_file) if jsonl_file else None
        self.dedup = dedup
        self.similarity_threshold = max(0.0, min(1.0, float(similarity_threshold)))
        self.repeat_after_sec = max(0.0, float(repeat_after_sec))
        self.multiline = multiline
        self.separator = separator

        self._lock = threading.Lock()
        self._last_norm: str = ""
        self._last_logged_at: float = 0.0

    def reset_dedup(self) -> None:
        with self._lock:
            self._last_norm = ""
            self._last_logged_at = 0.0

    def current_log_path(self, now: Optional[datetime] = None) -> Path:
        if self.fixed_log_file is not None:
            return self.fixed_log_file
        dt = now or datetime.now()
        return self.log_dir / f"ocr_{dt.strftime('%Y-%m-%d')}.log"

    def _is_duplicate(self, norm: str, mono_now: float) -> bool:
        if not self.dedup or not self._last_norm:
            return False
        if self.repeat_after_sec > 0 and (mono_now - self._last_logged_at) >= self.repeat_after_sec:
            return False
        if norm == self._last_norm:
            return True
        if self.similarity_threshold < 1.0:
            ratio = SequenceMatcher(None, self._last_norm, norm).ratio()
            return ratio >= self.similarity_threshold
        return False

    def log(
        self,
        lines: list[str],
        avg_confidence: float,
        elapsed_ms: float,
        region: Optional[dict[str, int]] = None,
    ) -> Optional[LogRecord]:
        cleaned_lines = [normalize_text(ln) for ln in lines if normalize_text(ln)]
        if not cleaned_lines:
            return None

        joined = self.separator.join(cleaned_lines)
        norm = normalize_text(joined)
        mono_now = time.monotonic()

        with self._lock:
            if self._is_duplicate(norm, mono_now):
                return None

            now = datetime.now()
            ts = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            log_path = self.current_log_path(now)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            record = LogRecord(
                timestamp=ts,
                text=joined,
                lines=cleaned_lines,
                avg_confidence=round(float(avg_confidence), 4),
                elapsed_ms=round(float(elapsed_ms), 1),
                region=region,
                log_path=str(log_path),
            )

            formatted = record.format_line(multiline=self.multiline, separator=self.separator)
            with log_path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(formatted + "\n")
                f.flush()

            if self.jsonl_file is not None:
                self.jsonl_file.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "timestamp": record.timestamp,
                    "text": record.text,
                    "lines": record.lines,
                    "avg_confidence": record.avg_confidence,
                    "elapsed_ms": record.elapsed_ms,
                    "region": record.region,
                }
                with self.jsonl_file.open("a", encoding="utf-8", newline="\n") as jf:
                    jf.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    jf.flush()

            self._last_norm = norm
            self._last_logged_at = mono_now
            return record
