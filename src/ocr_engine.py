from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

import cv2
import numpy as np
import onnxruntime as ort
import requests
from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

EngineName = Literal["vietocr", "rapidocr"]

_VIETOCR_BASE_URL = "https://huggingface.co/dzngo/vietocr-models/resolve/main/vietocr/"
_VIETOCR_FILES = (
    "encoder_w8.onnx",
    "decoder_init_w8.onnx",
    "decoder_step_w8.onnx",
    "vocab.txt",
)

_SOS_TOKEN = 1
_EOS_TOKEN = 2
_FIRST_CHAR_TOKEN = 4


@dataclass(frozen=True)
class OCRItem:
    text: str
    confidence: float
    box: tuple[int, int, int, int]  # (x1, y1, x2, y2)


@dataclass(frozen=True)
class OCRResult:
    items: list[OCRItem]
    lines: list[str]
    avg_confidence: float
    elapsed_ms: float

    @property
    def full_text(self) -> str:
        return "\n".join(self.lines)


def _ensure_vietocr_models(
    models_dir: Path,
    on_status: Optional[Callable[[str], None]] = None,
) -> Path:
    target_dir = models_dir / "vietocr"
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in _VIETOCR_FILES:
        dst = target_dir / filename
        if dst.exists() and dst.stat().st_size > 0:
            continue
        if on_status:
            on_status(f"Đang tải model VietOCR ({filename})...")
        tmp = dst.with_suffix(dst.suffix + ".part")
        with requests.get(_VIETOCR_BASE_URL + filename, stream=True, timeout=90) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
        tmp.replace(dst)
    return target_dir


def _sort_reading_order(boxes_xyxy: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Sort bounding boxes top-to-bottom, grouping horizontal items on the same visual line."""
    if len(boxes_xyxy) <= 1:
        return boxes_xyxy

    heights = [max(1, b[3] - b[1]) for b in boxes_xyxy]
    median_h = float(np.median(heights))
    row_tol = max(8.0, median_h * 0.55)

    indexed = sorted(boxes_xyxy, key=lambda b: ((b[1] + b[3]) * 0.5, b[0]))
    rows: list[list[tuple[int, int, int, int]]] = []
    row_centers: list[float] = []

    for box in indexed:
        cy = (box[1] + box[3]) * 0.5
        if rows and abs(cy - row_centers[-1]) <= row_tol:
            rows[-1].append(box)
            row_centers[-1] = float(np.mean([(b[1] + b[3]) * 0.5 for b in rows[-1]]))
        else:
            rows.append([box])
            row_centers.append(cy)

    ordered: list[tuple[int, int, int, int]] = []
    for row in rows:
        row.sort(key=lambda b: b[0])
        ordered.extend(row)
    return ordered


def _merge_line_items(items: list[OCRItem]) -> list[str]:
    """Merge OCR items sitting on the same horizontal row into single lines separated by spaces."""
    if not items:
        return []
    heights = [max(1, it.box[3] - it.box[1]) for it in items]
    row_tol = max(8.0, float(np.median(heights)) * 0.55)

    lines: list[str] = []
    current_row: list[OCRItem] = [items[0]]
    current_cy = (items[0].box[1] + items[0].box[3]) * 0.5

    for it in items[1:]:
        cy = (it.box[1] + it.box[3]) * 0.5
        if abs(cy - current_cy) <= row_tol:
            current_row.append(it)
            current_cy = float(np.mean([(x.box[1] + x.box[3]) * 0.5 for x in current_row]))
        else:
            current_row.sort(key=lambda x: x.box[0])
            lines.append(" ".join(x.text for x in current_row))
            current_row = [it]
            current_cy = cy

    current_row.sort(key=lambda x: x.box[0])
    lines.append(" ".join(x.text for x in current_row))
    return lines


class _VietOCRRecognizer:
    """KV-cached 8-bit ONNX VietOCR recognizer (full Vietnamese diacritics + English)."""

    def __init__(self, model_dir: Path, threads: int) -> None:
        self.vocab = (model_dir / "vocab.txt").read_text(encoding="utf-8").splitlines()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        providers = ["CPUExecutionProvider"]
        self.enc = ort.InferenceSession(str(model_dir / "encoder_w8.onnx"), sess_options=opts, providers=providers)
        self.dec_init = ort.InferenceSession(str(model_dir / "decoder_init_w8.onnx"), sess_options=opts, providers=providers)
        self.dec_step = ort.InferenceSession(str(model_dir / "decoder_step_w8.onnx"), sess_options=opts, providers=providers)

    @staticmethod
    def _preprocess(bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        new_h = 32
        new_w = max(32, min(512, int(math.ceil((w * new_h / max(1, h)) / 10.0) * 10)))
        interp = cv2.INTER_AREA if h > new_h else cv2.INTER_CUBIC
        resized = cv2.resize(rgb, (new_w, new_h), interpolation=interp)
        x = resized.astype(np.float32) / 255.0
        return np.transpose(x, (2, 0, 1))[None, ...]

    def recognize(self, bgr: np.ndarray, max_len: int = 128) -> tuple[str, float]:
        x = self._preprocess(bgr)
        memory = self.enc.run(None, {"image": x})[0]
        cross_k, cross_v = self.dec_init.run(None, {"memory": memory})

        past_k = np.zeros((6, 8, 0, 32), dtype=np.float32)
        past_v = np.zeros((6, 8, 0, 32), dtype=np.float32)

        token = _SOS_TOKEN
        chars: list[str] = []
        probs: list[float] = []
        vocab = self.vocab
        vocab_len = len(vocab)

        for pos in range(max_len):
            logits, past_k, past_v = self.dec_step.run(
                None,
                {
                    "token": np.array([token], dtype=np.int64),
                    "pos": np.array([pos], dtype=np.int64),
                    "past_k": past_k,
                    "past_v": past_v,
                    "cross_k": cross_k,
                    "cross_v": cross_v,
                },
            )
            max_l = float(np.max(logits))
            exps = np.exp(logits - max_l)
            prob_dist = exps / float(np.sum(exps))
            token = int(np.argmax(logits))
            if token == _EOS_TOKEN:
                break
            if _FIRST_CHAR_TOKEN <= token < vocab_len:
                chars.append(vocab[token])
                probs.append(float(prob_dist[token]))

        text = "".join(chars).strip()
        conf = float(np.mean(probs)) if probs else 0.0
        return text, conf


class ScreenOCREngine:
    """
    Hybrid CPU ONNX OCR engine:
      - 'vietocr'  : RapidOCR PP-OCRv6_det_tiny + VietOCR w8 ONNX (accurate Vietnamese + English)
      - 'rapidocr' : RapidOCR PP-OCRv6 end-to-end (fast English / Chinese / numbers)
    """

    def __init__(
        self,
        engine: EngineName = "vietocr",
        models_dir: Optional[Path] = None,
        min_confidence: float = 0.5,
        threads: Optional[int] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.engine_name: EngineName = engine
        self.min_confidence = float(min_confidence)
        self.threads = threads or min(4, max(1, (os.cpu_count() or 4) // 2))
        self.models_dir = Path(models_dir) if models_dir else Path(__file__).resolve().parent.parent / "models"

        # Silence noisy RapidOCR info logs during polling
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)

        if engine == "vietocr":
            if on_status:
                on_status("Đang khởi tạo detector PP-OCRv6 + VietOCR ONNX...")
            viet_dir = _ensure_vietocr_models(self.models_dir, on_status=on_status)
            self._detector = RapidOCR(
                params={
                    "Global.use_rec": False,
                    "Global.use_cls": False,
                    "Global.log_level": "warning",
                    "Det.engine_type": EngineType.ONNXRUNTIME,
                    "Det.ocr_version": OCRVersion.PPOCRV6,
                    "Det.model_type": ModelType.TINY,
                    "EngineConfig.onnxruntime.intra_op_num_threads": self.threads,
                }
            )
            self._recognizer: Optional[_VietOCRRecognizer] = _VietOCRRecognizer(viet_dir, threads=self.threads)
            self._rapid: Optional[RapidOCR] = None
        else:
            if on_status:
                on_status("Đang khởi tạo RapidOCR PP-OCRv6...")
            self._rapid = RapidOCR(
                params={
                    "Global.use_cls": False,
                    "Global.log_level": "warning",
                    "Det.engine_type": EngineType.ONNXRUNTIME,
                    "Det.ocr_version": OCRVersion.PPOCRV6,
                    "Det.model_type": ModelType.TINY,
                    "Rec.engine_type": EngineType.ONNXRUNTIME,
                    "EngineConfig.onnxruntime.intra_op_num_threads": self.threads,
                }
            )
            self._detector = None
            self._recognizer = None

    def read(self, bgr: np.ndarray) -> OCRResult:
        t0 = time.perf_counter()
        h, w = bgr.shape[:2]

        # Downscale oversized full-screen captures so CPU latency stays low
        scale = 1.0
        max_dim = max(h, w)
        if max_dim > 1600:
            scale = 1600.0 / max_dim
            work = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            work = bgr

        if self.engine_name == "vietocr":
            items = self._run_vietocr(work)
        else:
            items = self._run_rapidocr(work)

        # Filter by confidence and merge into visual rows
        items = [it for it in items if it.text and it.confidence >= self.min_confidence]
        lines = _merge_line_items(items)
        avg_conf = float(np.mean([it.confidence for it in items])) if items else 0.0
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return OCRResult(items=items, lines=lines, avg_confidence=avg_conf, elapsed_ms=elapsed_ms)

    def _run_vietocr(self, bgr: np.ndarray) -> list[OCRItem]:
        assert self._detector is not None and self._recognizer is not None
        det_res = self._detector(bgr)
        if det_res is None or det_res.boxes is None or len(det_res.boxes) == 0:
            return []

        h, w = bgr.shape[:2]
        raw_boxes: list[tuple[int, int, int, int]] = []
        for poly in det_res.boxes:
            xs = poly[:, 0]
            ys = poly[:, 1]
            x1 = max(0, int(np.floor(xs.min())))
            y1 = max(0, int(np.floor(ys.min())))
            x2 = min(w, int(np.ceil(xs.max())))
            y2 = min(h, int(np.ceil(ys.max())))
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                raw_boxes.append((x1, y1, x2, y2))

        ordered = _sort_reading_order(raw_boxes)
        items: list[OCRItem] = []
        for x1, y1, x2, y2 in ordered:
            bh = max(1, y2 - y1)
            pad_y = max(3, int(bh * 0.14))
            pad_x = max(4, int(bh * 0.14))
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y)
            cx2 = min(w, x2 + pad_x)
            cy2 = min(h, y2 + pad_y)
            crop = bgr[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue
            txt, conf = self._recognizer.recognize(crop)
            if txt:
                items.append(OCRItem(text=txt, confidence=conf, box=(x1, y1, x2, y2)))
        return items

    def _run_rapidocr(self, bgr: np.ndarray) -> list[OCRItem]:
        assert self._rapid is not None
        res = self._rapid(bgr)
        if res is None or not res.txts or res.boxes is None:
            return []

        items_with_boxes: list[tuple[tuple[int, int, int, int], str, float]] = []
        for poly, txt, score in zip(res.boxes, res.txts, res.scores):
            xs = poly[:, 0]
            ys = poly[:, 1]
            box = (
                int(np.floor(xs.min())),
                int(np.floor(ys.min())),
                int(np.ceil(xs.max())),
                int(np.ceil(ys.max())),
            )
            items_with_boxes.append((box, str(txt).strip(), float(score)))

        ordered_boxes = _sort_reading_order([b for b, _, _ in items_with_boxes])
        lookup: dict[tuple[int, int, int, int], list[tuple[str, float]]] = {}
        for box, txt, score in items_with_boxes:
            lookup.setdefault(box, []).append((txt, score))

        items: list[OCRItem] = []
        for box in ordered_boxes:
            txt, score = lookup[box].pop(0)
            if txt:
                items.append(OCRItem(text=txt, confidence=score, box=box))
        return items
