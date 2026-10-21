"""Regression coverage for safe source classification and reversible retranslation."""
from datetime import datetime

from novel_workflow.auto_chapter_review import (
    is_auxiliary_document, is_original_source_document,
)
from novel_workflow.models import NovelProfile
from novel_workflow.translation_progress import (
    completed_chapters, completed_chapter_count, confirmed_daily_activity,
    confirm_retranslation, daily_chapter_count, goal_progress,
    retranslation_preview, retranslation_context_candidate, record_translator_export, undo_retranslation,
)


def _export(profile, chapters, key, day):
    record_translator_export(
        profile, chapters, source_path="WSTTranslator.txt",
        digest="a" * 64, exported_path="export.txt", event_id=key,
        completed_at=datetime.fromisoformat(day),
    )


def test_auxiliary_names_never_count_as_chinese_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in (
        "WSTGlossary.txt", "WSTStyle.txt", "WSTPrompt.txt", "WSTContext.md",
        "WSTTranslator.txt", "WSTVocabulary.txt", "WSTNotes.txt",
    ):
        path = source / name
        path.write_text("第123章 词汇例句", encoding="utf-8")
        assert is_auxiliary_document(path)
        assert not is_original_source_document(path, {path.resolve()}, source)
    path = source / "WST.txt"
    path.write_text("第123章 正文", encoding="utf-8")
    assert not is_auxiliary_document(path)
    assert is_original_source_document(path, {path.resolve()}, source)


def test_context_retranslation_masks_only_prior_export_chapters_and_undo():
    profile = NovelProfile()
    _export(profile, list(range(1, 505)), "first", "2026-10-20T15:20:00")
    profile.translation_goal_target = 40
    assert retranslation_preview(profile, 475)["count"] == 30
    original = list(profile.translator_export_events[0]["chapters"])
    result = confirm_retranslation(profile, 475, context_chapter=474, reason="retry")
    assert result["event_count"] == 1
    assert completed_chapter_count(profile) == 474
    assert max(completed_chapters(profile)) == 474
    assert profile.translator_export_events[0]["chapters"] == original
    assert daily_chapter_count(profile, "2026-10-20") == 474
    assert goal_progress(profile) == (474, 40, 100)
    assert confirm_retranslation(profile, 475, context_chapter=474) is None
    _export(profile, [475, 476, 477], "second", "2026-10-21T12:30:00")
    assert completed_chapter_count(profile) == 477
    assert not 478 in completed_chapters(profile)
    assert daily_chapter_count(profile, "2026-10-21") == 3
    assert undo_retranslation(profile, result["reset_id"])
    assert completed_chapter_count(profile) == 504
    assert not undo_retranslation(profile, result["reset_id"])


def test_partial_event_reset_preserves_unaffected_chapters():
    profile = NovelProfile()
    _export(profile, [472, 473, 474, 475, 476], "one", "2026-10-20T12:00:00")
    reset = confirm_retranslation(profile, 475, context_chapter=474)
    assert reset["affected_chapters"] == [475, 476]
    assert completed_chapters(profile) == {472, 473, 474}
    assert confirmed_daily_activity(profile)["2026-10-20"] == {472, 473, 474}
    assert profile.translator_export_events[0]["chapters"] == [472, 473, 474, 475, 476]


def test_context_candidate_ignores_glossary_chapter_examples():
    text = "# Novel Text\nบทที่ 473 旧文\n正文\nบทที่ 474 完结\n正文\n# Glossary\n第999章 术语示例"
    assert retranslation_context_candidate(text) == (474, (473, 474))


def test_context_candidate_is_ambiguous_when_headings_jump():
    text = "บทที่ 470\n正文\nบทที่ 474\n正文"
    chapter, found = retranslation_context_candidate(text)
    assert chapter is None
    assert found == (470, 474)


def test_context_candidate_no_headings_and_non_novel_sections():
    assert retranslation_context_candidate("today 474 words") == (None, ())
    assert retranslation_context_candidate("# Glossary\n第999章 术语示例") == (None, ())
