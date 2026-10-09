"""Exercise the application's updater against the actual published release."""
import hashlib
from pathlib import Path
import sys
from novel_workflow.updater import check_for_update, download_update


def main():
    version, destination = sys.argv[1:]
    update = check_for_update('3.6.8', timeout=30)
    assert update and update.version == version
    published = download_update(update, Path(destination), timeout=60)
    built = Path('dist') / f'NovelWorkflow-Setup-{version}.exe'
    assert hashlib.sha256(published.read_bytes()).digest() == hashlib.sha256(built.read_bytes()).digest()
    print(f'Published updater PASS: v{version}, official origin, size {update.size}, SHA-256 {update.sha256}')


if __name__ == '__main__':
    main()
