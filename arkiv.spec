# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

datas = [(str(root / "ui"), "ui")]
binaries = []
hiddenimports = [
    "clr",
    "pythonnet",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "bottle",
    "proxy_tools",
    "pypdf",
    "docx",
    "openpyxl",
    "PIL",
    "watchdog",
    "watchdog.observers",
    "httpx",
    "arkiv",
    "arkiv.api",
    "arkiv.ai",
    "arkiv.config",
    "arkiv.db",
    "arkiv.files",
    "arkiv.paths",
    "arkiv.platform_open",
    "arkiv.service",
]

for package in ("webview", "pythonnet", "clr_loader"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Arkiv",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "packaging" / "arkiv.ico") if (root / "packaging" / "arkiv.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Arkiv",
)
