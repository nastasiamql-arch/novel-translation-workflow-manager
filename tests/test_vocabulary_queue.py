import pytest
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.vocabulary_queue import load_queue, save_queue, queue_path


def row(profile_id, identifier):
    return {'id': identifier, 'profile_id': profile_id, 'text': '李来福\tหลี่ไหลฝู',
            'count': 1, 'source_digest': 'digest'}


def test_profiles_persist_independently(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(), NovelProfile()
    repo.save_profile(a); repo.save_profile(b)
    save_queue(repo, a.id, {'version': 1, 'items': [row(a.id, 'a')]})
    save_queue(repo, b.id, {'version': 1, 'items': [row(b.id, 'b')]})
    reopened = ProjectRepository(tmp_path)
    assert load_queue(reopened, a.id)['items'][0]['id'] == 'a'
    save_queue(reopened, a.id, {'version': 1, 'items': []})
    assert load_queue(reopened, b.id)['items'][0]['id'] == 'b'


def test_invalid_queue_is_preserved(tmp_path):
    repo = ProjectRepository(tmp_path)
    p = NovelProfile(); repo.save_profile(p)
    path = queue_path(repo, p.id)
    path.write_text('{"version": 99, "items": []}', encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        save_queue(repo, p.id, {'version': 1, 'items': []})
    assert path.read_bytes() == original
