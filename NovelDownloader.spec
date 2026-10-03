from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = [
    *collect_submodules("novel_workflow.downloader"),
    *collect_submodules("novel_workflow.downloader_ui"),
]
datas = [
    ("src/novel_workflow/resources/palantir_novel.png", "novel_workflow/resources"),
    *copy_metadata("novelworkflow"),
]

a = Analysis(
    ["run_downloader.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["novel_workflow.workspace_window", "novel_workflow.main", "novel_workflow.ui"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NovelDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/palantir_novel.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="NovelDownloader",
)
