from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from .capture import CaptureRegion, enable_dpi_awareness, get_monitor_region, list_monitors
from .logger import LogRecord, OCRLogger
from .ocr_engine import EngineName, ScreenOCREngine
from .region_selector import load_saved_region, save_region, select_region_interactive
from .worker import ScreenOCRWorker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ocr-vcam",
        description="Đọc chữ trực tiếp từ vùng màn hình (OCR) và ghi log thời gian + nội dung ra file.",
    )
    p.add_argument("--gui", action="store_true", help="Mở giao diện điều khiển đồ họa (Tkinter).")
    p.add_argument("--list-monitors", action="store_true", help="Liệt kê danh sách màn hình và tọa độ.")
    p.add_argument("--select", action="store_true", help="Mở khung kéo chuột để chọn vùng màn hình.")
    p.add_argument("--reuse", action="store_true", help="Dùng lại vùng đã chọn gần nhất trong config.json.")
    p.add_argument("--region", type=str, default=None, help="Vùng chụp cố định dạng 'left,top,width,height'.")
    p.add_argument("--fullscreen", action="store_true", help="Quét toàn bộ màn hình chính (hoặc --monitor).")
    p.add_argument("--monitor", type=int, default=1, help="Số thứ tự màn hình (0=tất cả, 1=chính, 2+=phụ).")
    p.add_argument(
        "--engine",
        choices=["vietocr", "rapidocr"],
        default="vietocr",
        help="Engine OCR: 'vietocr' (Tiếng Việt có dấu + EN, mặc định) hoặc 'rapidocr' (nhanh đa ngôn ngữ).",
    )
    p.add_argument("--interval", type=float, default=0.5, help="Chu kỳ quét tính bằng giây (mặc định: 0.5).")
    p.add_argument("--min-conf", type=float, default=0.5, help="Ngưỡng độ tin cậy tối thiểu 0..1 (mặc định: 0.5).")
    p.add_argument(
        "--diff-threshold",
        type=float,
        default=1.2,
        help="Ngưỡng thay đổi pixel để bỏ qua khung tĩnh; đặt 0 để luôn OCR (mặc định: 1.2).",
    )
    p.add_argument("--out", type=str, default=None, help="File log đầu ra cố định (mặc định: logs/ocr_YYYY-MM-DD.log).")
    p.add_argument("--jsonl", type=str, default=None, help="Tùy chọn ghi thêm log JSONL có cấu trúc.")
    p.add_argument("--multiline", action="store_true", help="Giữ xuống dòng cho mỗi dòng OCR thay vì nối bằng ' | '.")
    p.add_argument("--no-dedup", action="store_true", help="Tắt lọc trùng lặp (ghi mọi lần quét kể cả nội dung giống hệt).")
    p.add_argument(
        "--repeat-after",
        type=float,
        default=0.0,
        help="Ghi lại nội dung giữ nguyên sau N giây (0 = chỉ ghi khi nội dung thay đổi).",
    )
    p.add_argument("--once", action="store_true", help="Chụp và đọc 1 lần duy nhất rồi thoát.")
    return p


def _resolve_region(args: argparse.Namespace) -> Optional[CaptureRegion]:
    if args.region:
        region = CaptureRegion.parse(args.region)
        save_region(DEFAULT_CONFIG, region)
        return region

    if args.fullscreen:
        return get_monitor_region(args.monitor)

    if args.reuse and not args.select:
        saved = load_saved_region(DEFAULT_CONFIG)
        if saved is not None:
            return saved
        print("[!] Chưa có vùng lưu trước đó trong config.json, mở khung chọn vùng...")

    if args.select or (not args.region and not args.fullscreen):
        region = select_region_interactive()
        if region is not None:
            save_region(DEFAULT_CONFIG, region)
        return region

    return get_monitor_region(args.monitor)


def main(argv: Optional[list[str]] = None) -> int:
    _configure_utf8_stdio()
    enable_dpi_awareness()
    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import launch_gui

        launch_gui()
        return 0

    if args.list_monitors:
        for idx, mon in enumerate(list_monitors()):
            tag = "Tất cả màn hình" if idx == 0 else f"Màn hình {idx}"
            print(f"[{idx}] {tag}: {mon.label()}")
        return 0

    region = _resolve_region(args)
    if region is None:
        print("Đã hủy chọn vùng.")
        return 1

    fixed_log = Path(args.out) if args.out else None
    jsonl_log = Path(args.jsonl) if args.jsonl else None

    logger = OCRLogger(
        log_dir=DEFAULT_LOG_DIR,
        fixed_log_file=fixed_log,
        jsonl_file=jsonl_log,
        dedup=not args.no_dedup,
        repeat_after_sec=args.repeat_after,
        multiline=args.multiline,
    )

    print(f"[OCR] Engine  : {args.engine}")
    print(f"[OCR] Vùng    : {region.label()}")
    print(f"[OCR] File log: {logger.current_log_path()}")
    if jsonl_log:
        print(f"[OCR] JSONL   : {jsonl_log}")

    engine_name: EngineName = args.engine
    engine = ScreenOCREngine(
        engine=engine_name,
        min_confidence=args.min_conf,
        on_status=lambda m: print(f"[OCR] {m}", flush=True),
    )

    def on_record(rec: LogRecord) -> None:
        print(rec.format_line(multiline=args.multiline), flush=True)

    def on_error(exc: Exception) -> None:
        print(f"[LỖI] {exc}", file=sys.stderr, flush=True)

    worker = ScreenOCRWorker(
        region=region,
        logger=logger,
        engine=engine,
        engine_name=engine_name,
        interval_sec=args.interval,
        min_confidence=args.min_conf,
        diff_threshold=args.diff_threshold,
        on_record=on_record,
        on_error=on_error,
    )

    if args.once:
        rec = worker.run_once()
        if rec is None:
            print("[OCR] Không phát hiện chữ trong vùng chọn.")
        return 0

    print("[OCR] Đang theo dõi màn hình... Nhấn Ctrl+C để dừng.\n", flush=True)
    worker.start()
    try:
        while worker.is_running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n[OCR] Đang dừng...", flush=True)
        worker.stop()

    print(
        f"[OCR] Hoàn tất — Quét: {worker.stats.scans} | Bỏ qua khung tĩnh: {worker.stats.skipped} | "
        f"Đã ghi: {worker.stats.logged} dòng -> {logger.current_log_path()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
