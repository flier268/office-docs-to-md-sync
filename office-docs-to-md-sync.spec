from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path.cwd()

datas = collect_data_files("app", includes=["static/*.html", "static/*.js", "static/*.css"])
datas += collect_data_files("markitdown_no_magika")

# `markitdown_no_magika` is used for Office conversion, so we include it
# detect it reliably unless we include it explicitly.
hiddenimports = collect_submodules("uvicorn")
hiddenimports += collect_submodules("markitdown_no_magika")


a = Analysis(
    ["run_app.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="office-docs-to-md-sync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="office-docs-to-md-sync",
)
