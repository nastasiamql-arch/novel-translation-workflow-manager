import json
from pathlib import Path

import pytest

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository


def api_result(new=(), update=()):
    return json.dumps({"NEW": list(new), "UPDATE": list(update)}, ensure_ascii=False)


def setup_run(tmp_path):
    from novel_workflow.models import VocabularySettings
    source = tmp_path / "source.txt"
    vocab = tmp_path / "vocab.tsv"
    extract = tmp_path / "extract.md"
    polish = tmp_path / "polish.txt"
    source.write_text("chapter", encoding="utf-8")
    vocab.write_bytes(b"source\ttarget\tnotes\r\nold\tbefore\t\r\n")
    extract.write_text("EXTRACT user instructions", encoding="utf-8")
    polish.write_text("POLISH user instructions", encoding="utf-8")
    return VocabularySettings(source_path=str(source), vocab_path=str(vocab),
        extract_prompt_path=str(extract), polish_prompt_path=str(polish), model="test"), vocab


def test_profile_settings_are_independent_and_legacy_migrates(tmp_path):
    repo = ProjectRepository(tmp_path)
    first, second = NovelProfile(name="A"), NovelProfile(name="B")
    assert hasattr(first, "vocabulary_settings")
    first.vocabulary_settings.source_path = "A.txt"
    repo.save_profile(first)
    repo.save_profile(second)
    loaded = {p.id: p for p in repo.list_profiles()}
    assert loaded[first.id].vocabulary_settings.source_path == "A.txt"
    assert loaded[second.id].vocabulary_settings.source_path == ""
    raw = json.loads((repo.profile_dir(first.id) / "profile.json").read_text("utf-8"))
    assert raw["schema_version"] == 3
    legacy_dir = repo.profile_dir("a" * 32)
    legacy_dir.mkdir()
    (legacy_dir / "profile.json").write_text('{"id":"' + "a" * 32 + '","name":"Legacy"}')
    repo.list_profiles()
    assert json.loads((legacy_dir / "profile.json").read_text(encoding="utf-8"))["schema_version"] == 3


def test_snapshot_errors_identify_unreadable_input_without_exposing_path_or_content(tmp_path):
    from novel_workflow.vocabulary import InputFileError, run_vocabulary
    from novel_workflow.models import VocabularySettings
    settings = VocabularySettings(source_path=str(tmp_path / "private-novel.txt"),
        vocab_path=str(tmp_path / "private-vocab.tsv"),
        extract_prompt_path=str(tmp_path / "private-extract.md"),
        polish_prompt_path=str(tmp_path / "private-polish.md"))
    with pytest.raises(InputFileError) as error:
        run_vocabulary(settings, object(), "unused")
    assert (error.value.role, error.value.reason) == ("source", "missing")
    assert "private-novel" not in str(error.value)


def test_snapshot_errors_classify_invalid_vocab_format(tmp_path):
    from novel_workflow.vocabulary import InputFileError, run_vocabulary
    settings, vocab = setup_run(tmp_path)
    vocab.write_text("not a valid header", encoding="utf-8")
    with pytest.raises(InputFileError) as error:
        run_vocabulary(settings, object(), "unused")
    assert (error.value.role, error.value.reason, error.value.detail) == ("vocab", "format", "SEGGlossary rows require at least 2 fields")


def test_headerless_seg_glossary_reads_characters_and_terms_with_different_widths(tmp_path):
    from novel_workflow.vocabulary import VocabDocument
    path = tmp_path / "SEGGlossary.txt"
    raw = ("人物甲\t人物译名\t男\t人物说明\r\n"
           "普通词\t词语译名\t词语说明\r\n").encode("utf-8")
    path.write_bytes(raw)
    document = VocabDocument.read(path, raw)
    assert document.kind == "seg-glossary"
    assert [len(row) for row in document.rows] == [4, 3]
    polished = json.dumps({"NEW": [["新词", "คำใหม่", "字段สาม", "字段四", "字段五"]],
                           "UPDATE": [{"before": ["普通词", "词语译名", "词语说明"],
                                       "after": ["普通词", "คำที่แก้", "คำอธิบายใหม่"]}]}, ensure_ascii=False)
    encoded, added, updated = document.merge(polished)
    assert encoded.decode("utf-8") == (
        "人物甲\t人物译名\t男\t人物说明\r\n"
        "普通词\tคำที่แก้\tคำอธิบายใหม่\r\n"
        "新词\tคำใหม่\t字段สาม\t字段四\t字段五\r\n")
    assert (added, updated) == (1, 1)


def test_seg_glossary_read_does_not_infer_fixed_column_meanings_from_sample(tmp_path):
    from novel_workflow.vocabulary import VocabDocument
    path = tmp_path / "SEGGlossary.txt"
    raw = "词一\tคำแปลหนึ่ง\tA\tB\tC\tD\tE\n词สอง\tคำแปลสอง\tความหมาย\n".encode("utf-8")
    document = VocabDocument.read(path, raw)
    assert document.rows == [["词一", "คำแปลหนึ่ง", "A", "B", "C", "D", "E"],
                             ["词สอง", "คำแปลสอง", "ความหมาย"]]


def test_seg_glossary_update_must_keep_the_existing_entry_shape(tmp_path):
    from novel_workflow.vocabulary import VocabDocument
    path = tmp_path / "SEGGlossary.txt"
    raw = "人物甲\t人物译名\t男\t人物说明\n".encode("utf-8")
    document = VocabDocument.read(path, raw)
    polished = json.dumps({"NEW": [], "UPDATE": [{"before": ["人物甲", "人物译名", "男", "人物说明"],
                                                    "after": ["人物甲", "คำแปล", "คำอธิบาย"]}]}, ensure_ascii=False)
    with pytest.raises(ValueError, match="preserve the row field count"):
        document.merge(polished)


def test_seg_glossary_allows_same_source_with_context_specific_entries(tmp_path):
    from novel_workflow.vocabulary import VocabDocument
    path = tmp_path / "SEGGlossary.txt"
    raw = "同名\tครอบครัวจาง\t-\tคำอธิบายหนึ่ง\n同名\tตระกูลจาง\t-\tคำอธิบายสอง\n".encode("utf-8")
    document = VocabDocument.read(path, raw)
    assert len(document.rows) == 2
    polished = json.dumps({"NEW": [], "UPDATE": [{
        "before": ["同名", "ครอบครัวจาง", "-", "คำอธิบายหนึ่ง"],
        "after": ["同名", "ครอบครัวจาง", "-", "แก้เฉพาะความหมายแรก"]
    }]}, ensure_ascii=False)
    encoded, added, updated = document.merge(polished)
    assert encoded.decode("utf-8") == "同名\tครอบครัวจาง\t-\tแก้เฉพาะความหมายแรก\n同名\tตระกูลจาง\t-\tคำอธิบายสอง\n"
    assert (added, updated) == (0, 1)


def test_seg_glossary_pipeline_uses_selected_prompts_and_prompt_driven_rows(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    from novel_workflow.models import VocabularySettings
    source, vocab = tmp_path / "source.txt", tmp_path / "SEGGlossary.txt"
    extract, polish = tmp_path / "extract.md", tmp_path / "polish.md"
    source.write_text("chapter source", encoding="utf-8")
    original = "person\tชื่อ\tเพศ\tรายละเอียดตัวละคร\nterm\tคำศัพท์\tรายละเอียดคำศัพท์\n"
    vocab.write_text(original, encoding="utf-8")
    extract.write_text("EXTRACT: find according to these rules", encoding="utf-8")
    polish.write_text("POLISH: format each type according to these rules", encoding="utf-8")
    settings = VocabularySettings(source_path=str(source), vocab_path=str(vocab),
        extract_prompt_path=str(extract), polish_prompt_path=str(polish), model="test")
    calls = []
    class Provider:
        def complete(self, model, prompt, key):
            calls.append(prompt)
            if len(calls) == 1: return "intermediate extraction"
            return json.dumps({"NEW": [["new term", "คำใหม่", "ข้อมูลหนึ่ง", "ข้อมูลสอง", "ข้อมูลสาม"]],
                "UPDATE": [{"before": ["term", "คำศัพท์", "รายละเอียดคำศัพท์"],
                            "after": ["term", "คำที่เกลาแล้ว", "รายละเอียดตาม Prompt"]}]}, ensure_ascii=False)
    result = run_vocabulary(settings, Provider(), "key")
    assert "EXTRACT: find according to these rules" in calls[0]
    assert "POLISH: format each type according to these rules" in calls[1]
    assert "Follow the selected Extract and Polish prompts" in calls[0]
    assert "Follow the selected Extract and Polish prompts" in calls[1]
    assert result.added == 1 and result.updated == 1
    assert "new term\tคำใหม่\tข้อมูลหนึ่ง\tข้อมูลสอง\tข้อมูลสาม" in vocab.read_text(encoding="utf-8")


def test_extract_cannot_write_and_polish_controls_commit(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    settings, vocab = setup_run(tmp_path)
    original = vocab.read_bytes()
    calls = []
    class Provider:
        def complete(self, model, prompt, key):
            assert vocab.read_bytes() == original
            calls.append(prompt)
            return api_result(new=[{"source": "discard" if len(calls) == 1 else "new", "target": "after", "notes": ""}])
    result = run_vocabulary(settings, Provider(), "secret")
    assert len(calls) == 2
    assert "EXTRACT user instructions" in calls[0]
    assert "POLISH user instructions" in calls[1] and "discard" in calls[1]
    assert "discard" not in vocab.read_text("utf-8")
    assert "new\tafter" in vocab.read_text("utf-8")
    assert Path(result.backup_path).read_bytes() == original
    assert result.added == 1 and result.updated == 0


@pytest.mark.parametrize("output", [
    'not json', api_result(new=[{"source":"old","target":"x","notes":""}]),
    api_result(update=[{"source":"missing","target":"x","notes":""}]),
    api_result(new=[{"source":"x","target":"x","notes":""}] * 2),
    api_result(new=[{"source":"x","target":"","notes":""}]),
    api_result(new=[{"source":"x","target":"y\nz","notes":""}]),
])
def test_invalid_polish_never_changes_original(tmp_path, output):
    from novel_workflow.vocabulary import run_vocabulary
    settings, vocab = setup_run(tmp_path)
    original = vocab.read_bytes()
    class Provider:
        def complete(self, *args): return output
    with pytest.raises(ValueError): run_vocabulary(settings, Provider(), "key")
    assert vocab.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("vocab_backups/*"))


def test_concurrent_change_is_preserved(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    settings, vocab = setup_run(tmp_path)
    class Provider:
        def complete(self, *args):
            vocab.write_text("external change", encoding="utf-8")
            return api_result(new=[{"source":"new","target":"x","notes":""}])
    with pytest.raises(ValueError, match="changed"):
        run_vocabulary(settings, Provider(), "key")
    assert vocab.read_text("utf-8") == "external change"


def test_atomic_failure_keeps_original_and_backup(tmp_path, monkeypatch):
    from novel_workflow import vocabulary
    settings, vocab = setup_run(tmp_path)
    original = vocab.read_bytes()
    class Provider:
        def complete(self, *args): return api_result(new=[{"source":"new","target":"x","notes":""}])
    def fail(*args): raise OSError("replace failed")
    monkeypatch.setattr(vocabulary.os, "replace", fail)
    with pytest.raises(OSError): vocabulary.run_vocabulary(settings, Provider(), "key")
    assert vocab.read_bytes() == original
    assert len(list(tmp_path.glob("vocab_backups/*"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_json_repair_preserves_string_commas_and_original(tmp_path):
    from novel_workflow.vocabulary import read_prompt
    path = tmp_path / "prompt.json"
    raw = '{"instruction":"literal ,} and ,]",}'
    path.write_text(raw, encoding="utf-8")
    assert 'literal ,} and ,]' in read_prompt(path)
    assert path.read_text("utf-8") == raw


def test_docx_prompt_reads_paragraphs_and_tables(tmp_path):
    import zipfile
    from novel_workflow.vocabulary import read_prompt
    path = tmp_path / "prompt.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>หาศัพท์</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>table prompt</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    assert "หาศัพท์" in read_prompt(path) and "table prompt" in read_prompt(path)


def test_update_and_noop_preserve_format(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    settings, vocab = setup_run(tmp_path)
    class Provider:
        def complete(self, *args): return api_result(update=[{"source":"old","target":"after","notes":"changed"}])
    result = run_vocabulary(settings, Provider(), "key")
    assert result.updated == 1
    assert vocab.read_bytes() == b"source\ttarget\tnotes\r\nold\tafter\tchanged\r\n"
    original = vocab.read_bytes()
    class Empty:
        def complete(self, *args): return api_result()
    result = run_vocabulary(settings, Empty(), "key")
    assert result.backup_path is None and vocab.read_bytes() == original


def test_storage_recovery_does_not_change_literals(tmp_path):
    from novel_workflow.storage import read_json
    path = tmp_path / "profile.json"
    raw = '{"name":"literal ,} and ,]",}'
    path.write_text(raw, encoding="utf-8")
    assert read_json(path, {})["name"] == "literal ,} and ,]"
    assert path.read_text("utf-8") == raw


def test_json_vocab_repair_and_bom_are_validated_before_commit(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    settings, _ = setup_run(tmp_path)
    path = tmp_path / "vocab.json"
    raw = b'\xef\xbb\xbf[{"source":"a","target":"b","notes":"literal ,}",},]'
    path.write_bytes(raw)
    settings.vocab_path = str(path)
    class Provider:
        def complete(self, *args): return api_result(new=[{"source":"new","target":"after","notes":""}])
    result = run_vocabulary(settings, Provider(), "key")
    assert Path(result.backup_path).read_bytes() == raw
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    assert json.loads(path.read_text("utf-8-sig"))[0]["notes"] == "literal ,}"


def test_source_is_snapshot_for_both_stages(tmp_path):
    from novel_workflow.vocabulary import run_vocabulary
    settings, _ = setup_run(tmp_path)
    calls = []
    class Provider:
        def complete(self, model, prompt, key):
            calls.append(prompt)
            Path(settings.source_path).write_text("replaced source", encoding="utf-8")
            return api_result()
    run_vocabulary(settings, Provider(), "key")
    assert len(calls) == 2 and all("chapter" in prompt and "replaced source" not in prompt for prompt in calls)
