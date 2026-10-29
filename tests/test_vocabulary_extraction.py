import pytest

from novel_workflow.vocabulary_extraction import extract_new_vocabulary


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_extracts_preserving_rows_and_novel(newline):
    novel = newline.join(['บทที่ 349', '李来福 อยู่ในเนื้อเรื่อง', '[จบบท]']) + newline
    rows = ['李来福\tหลี่ไหลฝู\tชาย\tเด็กหนุ่ม', '来福    ไหลฝู    ชาย    ชื่อเรียก',
            '来福    ไหลฝู    ชาย    ชื่อเรียก']
    original = novel + newline + 'คำศัพท์ใหม่' + newline + newline.join(rows) + newline
    result = extract_new_vocabulary(original)
    assert result.original_text == original
    assert result.cleaned_text == novel
    assert result.vocabulary_text == newline.join(rows)
    assert result.vocabulary_count == 3
    assert result.status == 'extracted'


def test_empty_and_absent_sections():
    original = 'บทที่ 1\nเนื้อหา\n\nคำศัพท์ใหม่\n[-]\n'
    result = extract_new_vocabulary(original)
    assert result.cleaned_text == 'บทที่ 1\nเนื้อหา\n'
    assert result.status == 'empty' and not result.has_vocabulary
    assert extract_new_vocabulary('เนื้อหา\n').cleaned_text == 'เนื้อหา\n'


def test_many_rows():
    rows = [f'词条\tคำศัพท์ {i}' for i in range(120)]
    result = extract_new_vocabulary('เนื้อหา\n\nคำศัพท์ใหม่\n' + '\n'.join(rows))
    assert result.vocabulary_count == 120
    assert result.vocabulary_text == '\n'.join(rows)


def test_multiple_chapters_with_verified_boundaries():
    text = ('บทที่ 1\nเรื่องหนึ่ง\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\n\n'
            'บทที่ 2\nเรื่องสอง\n\nคำศัพท์ใหม่\n来福\tไหลฝู\n')
    result = extract_new_vocabulary(text)
    assert result.cleaned_text == 'บทที่ 1\nเรื่องหนึ่ง\n\nบทที่ 2\nเรื่องสอง\n'
    assert result.vocabulary_text == '李来福\tหลี่ไหลฝู\n来福\tไหลฝู'
    assert result.vocabulary_count == 2


@pytest.mark.parametrize('text', [
    'เนื้อหา\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู',
    'เนื้อหา\n\nคำศัพท์ใหม่\nข้อความนิยายต่อไป',
    'เนื้อหา\n\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\nบทที่ 2\nเนื้อหา',
    'เนื้อหา\n\nคำศัพท์ใหม่\n[-]\n\nคำศัพท์ใหม่\n[-]',
    'เนื้อหา\n\nคำศัพท์ใหม่\n',
])
def test_ambiguous_input_is_untouched(text):
    result = extract_new_vocabulary(text)
    assert result.status == 'ambiguous'
    assert result.original_text == result.cleaned_text == text
    assert not result.has_vocabulary


@pytest.mark.parametrize('marker', ['[จบตอน]', '[จบบท]'])
@pytest.mark.parametrize('heading', ['คำศัพท์ใหม่', 'คำศัพท์ใหม่:', 'คำศัพท์ใหม่：'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_verified_chapter_end_without_blank_line(marker, heading, newline):
    original = newline.join(['บทที่ 750', 'เนื้อหานิยาย 李来福', marker]) + newline
    rows = ['李来福\tหลี่ไหลฝู\tชาย\tตัวละครหลัก',
            '来福    ไหลฝู    ชาย    ชื่อเรียกสั้น',
            '李来福 หลี่ไหลฝู ชาย ตัวละครหลัก']
    text = original + heading + newline + newline.join(rows)
    result = extract_new_vocabulary(text)
    assert result.original_text == text
    assert result.cleaned_text == original
    assert result.vocabulary_text == newline.join(rows)
    assert result.vocabulary_count == 3
    assert result.status == 'extracted'


@pytest.mark.parametrize('marker', ['[จบตอน]', '[จบบท]'])
def test_verified_chapter_end_empty_vocabulary_without_final_newline(marker):
    novel = f'บทที่ 750\nเนื้อหา\n{marker}\n'
    result = extract_new_vocabulary(novel + 'คำศัพท์ใหม่\n[-]')
    assert result.status == 'empty'
    assert result.cleaned_text == novel
    assert result.vocabulary_text == ''
    assert result.vocabulary_count == 0


def test_utf8_bom_and_crlf_remain_lossless():
    original = '\ufeffบทที่ 750\r\nเนื้อหา\r\n[จบตอน]\r\n'
    result = extract_new_vocabulary(
        original + 'คำศัพท์ใหม่：\r\n李来福\tหลี่ไหลฝู')
    assert result.status == 'extracted'
    assert result.cleaned_text == original
    assert result.vocabulary_text == '李来福\tหลี่ไหลฝู'
    assert extract_new_vocabulary(original).cleaned_text == original


def test_two_chapters_with_end_marker_sections():
    text = ('บทที่ 1\nเรื่องหนึ่ง\n[จบตอน]\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\n\n'
            'บทที่ 2\nเรื่องสอง\n[จบบท]\nคำศัพท์ใหม่\n来福\tไหลฝู')
    result = extract_new_vocabulary(text)
    assert result.status == 'extracted'
    assert result.vocabulary_count == 2
    assert result.vocabulary_text == '李来福\tหลี่ไหลฝู\n来福\tไหลฝู'
    assert result.cleaned_text == 'บทที่ 1\nเรื่องหนึ่ง\n[จบตอน]\nบทที่ 2\nเรื่องสอง\n[จบบท]\n'


@pytest.mark.parametrize('text', [
    'บทที่ 1\n李来福 เดินกลับเข้าบ้าน\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู',
    'บทที่ 1\nเนื้อหา\n[จบตอน] และต่อไป\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู',
    'บทที่ 1\nเนื้อหา\n[จบตอน]\nคำศัพท์ใหม่\n李来福 เดินกลับเข้าบ้าน',
    'บทที่ 1\nเนื้อหา\n[จบตอน]\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\nประโยคนิยายต่อ',
    'บทที่ 1\nเนื้อหา\n[จบตอน]\nคำศัพท์ใหม่\n李来福\tหลี่ไหลฝู\nคำศัพท์ใหม่\n来福\tไหลฝู',
])
def test_verified_end_rejects_ambiguous_rows_or_boundaries(text):
    result = extract_new_vocabulary(text)
    assert result.status == 'ambiguous'
    assert result.original_text == result.cleaned_text == text
    assert result.vocabulary_count == 0


def test_heading_inside_a_story_sentence_is_not_a_section():
    original = 'บทที่ 750\nตัวละครกล่าวถึงคำศัพท์ใหม่ในบทสนทนา\n李来福 เดินกลับเข้าบ้าน'
    result = extract_new_vocabulary(original)
    assert result.status == 'none'
    assert result.cleaned_text == original
