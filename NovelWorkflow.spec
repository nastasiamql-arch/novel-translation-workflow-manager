from PyInstaller.utils.hooks import collect_submodules, copy_metadata
from pathlib import Path
import tomllib

project_root = Path(SPECPATH)
with (project_root / 'pyproject.toml').open('rb') as project_file:
    build_version = tomllib.load(project_file)['project']['version']
version_file = project_root / 'build' / 'app-version.txt'
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(build_version, encoding='utf-8')

hiddenimports = collect_submodules('novel_workflow')
datas = [
    (str(version_file), 'novel_workflow/resources'),
    ('src/novel_workflow/resources/novelworkflow.png', 'novel_workflow/resources'),
    ('src/novel_workflow/resources/palantir_novel.png', 'novel_workflow/resources'),
    *[(str(path), 'novel_workflow/resources') for path in (project_root / 'src/novel_workflow/resources').glob('*.svg')],
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
