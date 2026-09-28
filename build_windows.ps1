$ErrorActionPreference = "Stop"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m PyInstaller --noconfirm --clean NovelWorkflow.spec
Compress-Archive -Path dist\NovelWorkflow\* -DestinationPath dist\NovelWorkflow-windows.zip -Force
