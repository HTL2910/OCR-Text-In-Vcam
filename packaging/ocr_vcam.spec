# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec building shared --onedir bundle with GUI + CLI executables and offline ONNX models."""
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)
import rapidocr

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ICON_PATH = PROJECT_ROOT / "assets" / "app.ico"
VIETOCR_DIR = PROJECT_ROOT / "models" / "vietocr"
RAPIDOCR_MODELS_DIR = Path(rapidocr.__file__).resolve().parent / "models"

datas = []
# Bundle RapidOCR YAML configs (exclude rapidocr/models/* so we only ship required ONNX files)
for src_file, dest_dir in collect_data_files("rapidocr"):
    if "\\models\\" in src_file or "/models/" in src_file:
        continue
    datas.append((src_file, dest_dir))

# Bundle required RapidOCR ONNX models
for model_name in ("PP-OCRv6_det_tiny.onnx", "PP-OCRv6_rec_small.onnx"):
    mf = RAPIDOCR_MODELS_DIR / model_name
    if mf.exists():
        datas.append((str(mf), "models/rapidocr"))

# Bundle VietOCR w8 KV-cached ONNX models + vocab
for fname in ("encoder_w8.onnx", "decoder_init_w8.onnx", "decoder_step_w8.onnx", "vocab.txt"):
    vf = VIETOCR_DIR / fname
    if not vf.exists():
        raise FileNotFoundError(f"Missing required VietOCR model file: {vf}")
    datas.append((str(vf), "models/vietocr"))

# Bundle app icon for runtime Tkinter titlebar
if ICON_PATH.exists():
    datas.append((str(ICON_PATH), "assets"))

datas += collect_data_files("onnxruntime")

binaries = []
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("shapely")
binaries += collect_dynamic_libs("cv2")

hiddenimports = (
    collect_submodules("rapidocr")
    + collect_submodules("onnxruntime.capi")
    + [
        "cv2",
        "mss",
        "mss.windows",
        "PIL.ImageGrab",
        "PIL._tkinter_finder",
        "pyclipper",
        "shapely",
        "shapely.geometry",
        "omegaconf",
        "yaml",
        "colorlog",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ]
)

excludes = [
    "torch",
    "torchvision",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "jupyter",
    "pytest",
]

a_gui = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_gui.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

a_cli = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entry_cli.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

MERGE(
    (a_gui, "OCR-Text-In-Vcam", "OCR-Text-In-Vcam"),
    (a_cli, "ocr-vcam-cli", "ocr-vcam-cli"),
)

pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="OCR-Text-In-Vcam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="ocr-vcam-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OCR-Text-In-Vcam",
)
