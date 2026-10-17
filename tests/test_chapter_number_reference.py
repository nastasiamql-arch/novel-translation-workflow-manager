"""Translator reference for source renumbering is profile-bound and read-only."""
from pathlib import Path

from novel_workflow.chapter_numbering import scan_chapters
from novel_workflow.chapter_number_reference import resolve_translator_reference, should_auto_propose
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository


def _profile(repo, name, translator_name, chapter):
    profile = NovelProfile(name=name)
    file = repo.profile_dir(profile.id) / translator_name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f"บทที่ {chapter}\nงานแปลไทย", encoding="utf-8")
    profile.working_files = [StepFile(path=file.name)]
    repo.save_profile(profile)
    return profile, file


def test_propose_from_matching_translator_and_other_novel_does_not_leak(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, trans_a = _profile(repo, "SEG", "SEGTranslator.txt", 545)
    b, trans_b = _profile(repo, "OTHER", "OTHERTranslator.txt", 899)
    source = repo.profile_dir(a.id) / "SEG.txt"
    source.write_text("第566章 支援主力\n正文\n第567章 万米法相", encoding="utf-8")
    ref = resolve_translator_reference(repo, a.id, source)
    assert ref.latest == 545 and ref.start == 546 and ref.path == trans_a
    assert should_auto_propose(scan_chapters(source.read_text(encoding="utf-8")), ref.start)
    assert resolve_translator_reference(repo, b.id, source).start is None


def test_unsaved_translator_edits_take_precedence(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, file = _profile(repo, "SEG", "SEGTranslator.txt", 545)
    source = repo.profile_dir(a.id) / "SEG.txt"
    ref = resolve_translator_reference(repo, a.id, source, {file.resolve(): "บทที่ 550\n"})
    assert ref.latest == 550 and ref.start == 551
    assert file.read_text(encoding="utf-8").startswith("บทที่ 545")


def test_no_translator_falls_back_to_manual_not_context(tmp_path):
    repo = ProjectRepository(tmp_path)
    a = NovelProfile(name="SEG")
    context = repo.profile_dir(a.id) / "Context.md"
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text("บทที่ 999", encoding="utf-8")
    a.context_path = str(context)
    repo.save_profile(a)
    ref = resolve_translator_reference(repo, a.id, context.parent / "SEG.txt")
    assert ref.start is None and ref.latest is None


def test_ambiguous_translator_is_not_guessed(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, first = _profile(repo, "SEG", "FirstTranslator.txt", 544)
    second = first.parent / "OtherTranslator.txt"
    second.write_text("บทที่ 545", encoding="utf-8")
    a.working_files.append(StepFile(path=second.name))
    repo.save_profile(a)
    ref = resolve_translator_reference(repo, a.id, first.parent / "SEG.txt")
    assert ref.start is None
    assert "หลายไฟล์" in ref.message


def test_does_not_resequence_old_chapters_or_existing_gaps():
    assert not should_auto_propose(scan_chapters("第4章\n第5章"), 546)
    assert not should_auto_propose(scan_chapters("第566章\n第568章"), 546)
    assert not should_auto_propose(scan_chapters("第566章\n第566章"), 546)
    assert not should_auto_propose([], 546)

def test_translator_current_progress_overrides_old_higher_export(tmp_path):
    repo = ProjectRepository(tmp_path)
    p, trans = _profile(repo, "SEG", "SEGTranslator.txt", 675)
    p.translator_export_events = [{
        "status": "committed", "profile_id": p.id, "translator_path": str(trans.resolve()),
        "chapters": list(range(686, 691)), "event_id": "old-revision",
    }]
    repo.save_profile(p)
    src = repo.profile_dir(p.id) / "SEG.txt"
    src.write_text("第691章 新的原文", encoding="utf-8")
    ref = resolve_translator_reference(repo, p.id, src)
    assert ref.latest == 675 and ref.start == 676
    assert "690" in ref.message and "ประวัติเดิม" in ref.message
    trans.write_text("没有可识别的章节标题", encoding="utf-8")
    assert resolve_translator_reference(repo, p.id, src).start is None
