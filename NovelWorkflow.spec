from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('novel_workflow')
a = Analysis(['run_app.py'], pathex=['src'], binaries=[], datas=[], hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='NovelWorkflow',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False)
