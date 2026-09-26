from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('novel_workflow')
datas = [('src/novel_workflow/resources/novelworkflow.png', 'novel_workflow/resources')]
a = Analysis(['run_app.py'], pathex=['src'], binaries=[], datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='NovelWorkflow',
          icon='assets/novelworkflow.ico', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=True, console=False)
