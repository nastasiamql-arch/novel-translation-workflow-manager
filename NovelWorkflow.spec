from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = [
    module for module in collect_submodules('novel_workflow')
    if not module.startswith((
        'novel_workflow.downloader',
    ))
]
datas = [
    ('src/novel_workflow/resources/novelworkflow.png', 'novel_workflow/resources'),
    ('src/novel_workflow/resources/palantir_novel.png', 'novel_workflow/resources'),
    *copy_metadata('novelworkflow'),
]

a = Analysis(
    ['run_app.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["novel_workflow.downloader", "novel_workflow.downloader_ui", "novel_workflow.downloader_main"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NovelWorkflow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/palantir_novel.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='NovelWorkflow',
)
