from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('novel_workflow')
datas = [('src/novel_workflow/resources/novelworkflow.png', 'novel_workflow/resources')]

a = Analysis(
    ['run_app.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    icon='assets/novelworkflow.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='NovelWorkflow',
)
