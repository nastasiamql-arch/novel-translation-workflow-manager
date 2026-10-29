"""Profile-scoped, temporary vocabulary waiting for external review."""
from pathlib import Path
from .storage import read_json, write_json


def queue_path(repo, profile_id):
    return repo.profile_dir(profile_id) / 'pending_vocabulary.json'


def load_queue(repo, profile_id):
    path = queue_path(repo, profile_id)
    if path.exists() and not path.read_bytes().strip():
        raise ValueError('ไฟล์คำศัพท์รอตรวจว่างหรือเสียหาย · เก็บข้อมูลเดิมไว้')
    data = read_json(path, {'version': 1, 'items': []})
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), list):
        raise ValueError('ข้อมูลคำศัพท์รอตรวจไม่ถูกต้อง · เก็บข้อมูลเดิมไว้')
    for row in data['items']:
        if (not isinstance(row, dict) or row.get('profile_id') != profile_id
                or not isinstance(row.get('id'), str) or not isinstance(row.get('text'), str)
                or type(row.get('count')) is not int or row['count'] < 1
                or not isinstance(row.get('source_digest'), str)):
            raise ValueError('ข้อมูลคำศัพท์รอตรวจไม่ถูกต้อง · เก็บข้อมูลเดิมไว้')
    return data


def save_queue(repo, profile_id, data):
    with repo.profile_lock:
        # Validate the existing file before replacing it.
        load_queue(repo, profile_id)
        write_json(queue_path(repo, profile_id), data)
