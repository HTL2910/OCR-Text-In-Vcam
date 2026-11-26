# OCR Text In Vcam

Công cụ đọc chữ trực tiếp từ vùng màn hình Windows (hỗ trợ đầy đủ **Tiếng Việt có dấu + Tiếng Anh**, chạy tốt trên cả nền sáng/tối hoặc video/VCam) và tự động ghi log kèm dấu thời gian vào file.

## Tính năng chính

- **Pipeline ONNX thuần CPU (không cần PyTorch/GPU):**
  - `vietocr` *(mặc định)*: Kết hợp **RapidOCR PP-OCRv6_det_tiny** (phát hiện chữ trên nền bất kỳ) + **VietOCR w8 KV-cached ONNX** (nhận dạng chính xác tiếng Việt có dấu & tiếng Anh).
  - `rapidocr`: Chế độ đa ngôn ngữ nhanh (Anh/Trung/số).
- **Chọn vùng màn hình chuẩn DPI:** Kéo chuột chọn vùng trên mọi màn hình (`Per-Monitor DPI Aware v2`), tự lưu tọa độ vào `config.json` để dùng lại.
- **Tối ưu CPU & Log sạch:**
  - `FrameDiffer` bỏ qua khung hình không đổi (<1ms) để không tốn CPU.
  - `OCRLogger` ghi UTF-8 tức thì (`flush()` mỗi dòng) vào `logs/ocr_YYYY-MM-DD.log`, lọc trùng lặp chính xác (không nuốt thay đổi nhỏ như mã số/OTP), hỗ trợ ghi thêm `.jsonl`.

## Cách chạy

### 1. Giao diện điều khiển (GUI)
Nhấp đúp `run_gui.bat` hoặc chạy:
```powershell
.\.venv\Scripts\python.exe -m src.gui
```

### 2. Dòng lệnh (CLI)
```powershell
# Kéo chuột chọn vùng rồi theo dõi liên tục
.\run_cli.bat

# Dùng lại vùng đã chọn lần trước, quét mỗi 0.3 giây
.\run_cli.bat --reuse --interval 0.3

# Quét vùng cố định (left,top,width,height) và ghi thêm JSONL
.\run_cli.bat --region 100,200,800,300 --out logs\session.log --jsonl logs\session.jsonl

# Chụp & ghi 1 lần duy nhất toàn màn hình chính
.\run_cli.bat --fullscreen --once
```

## Định dạng file log

Mặc định lưu tại `logs/ocr_YYYY-MM-DD.log`:
```text
[2026-11-26 13:52:04.128] Quay đầu sang trái và mỉm cười | Nháy mắt 2 lần để xác thực khuôn mặt
[2026-11-26 13:52:07.610] Code: 849201 - Status: Verified OK
```
