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


@pytest.mark.parametrize('row', [
    '枪支弹药 อาวุธปืนและกระสุน - อาวุธปืนและเครื่องกระสุน',
    '领导包间 ห้องอาหารส่วนตัวสำหรับหัวหน้า - ห้องรับประทานอาหาร',
    '李来福： หลี่ไหลฝู - ตัวละครหลัก',
    '李来福: หลี่ไหลฝู',
    '李来福 - หลี่ไหลฝู - ตัวละครหลัก',
    '李来福 → หลี่ไหลฝู',
    '李来福 = หลี่ไหลฝู',
    '李来福 | หลี่ไหลฝู',
    '1. 李来福 - หลี่ไหลฝู',
    '2) 李来福: หลี่ไหลฝู',
    '- 李来福: หลี่ไหลฝู',
    '* 李来福：หลี่ไหลฝู',
    '• 李来福 - หลี่ไหลฝู',
    '**李来福**：หลี่ไหลฝู',
    '李来福 หลี่ไหลฝู ชาย ตัวละครหลัก',
    '李来福\tหลี่ไหลฝู\tชาย\tตัวละครหลัก',
    '李来福    หลี่ไหลฝู    ชาย    ตัวละครหลัก',
])
@pytest.mark.parametrize('marker', ['[จบตอน]', '[จบบท]'])
def test_varied_vocab_rows_after_verified_end(row, marker):
    novel = 'บทที่ 750\nเนื้อหานิยาย\n' + marker + '\n'
    result = extract_new_vocabulary(novel + 'คำศัพท์ใหม่\n' + row)
    assert result.status == 'extracted'
    assert result.cleaned_text == novel
    assert result.vocabulary_text == row
    assert result.vocabulary_count == 1


def test_markdown_table_preserves_raw_layout_and_counts_lines():
    novel = 'บทที่ 750\nจบเรื่อง\n[จบตอน]\n'
    table = ('| 中文 | ไทย | คำอธิบาย |\n'
             '| --- | --- | --- |\n'
             '| 李来福 | หลี่ไหลฝู | ตัวละคร |\n'
             '| 来福 | ไหลฝู | ชื่อเรียก |')
    result = extract_new_vocabulary(novel + 'คำศัพท์ใหม่\n' + table)
    assert result.status == 'extracted'
    assert result.cleaned_text == novel
    assert result.vocabulary_count == 4  # Counts copied nonempty lines, not inferred words.
    assert result.vocabulary_text == table


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_mixed_rows_keep_duplicates_and_line_endings(newline):
    novel = newline.join(['บทที่ 750', 'ข้อความ', '[จบตอน]']) + newline
    rows = ['李来福\tหลี่ไหลฝู', '枪支弹药 อาวุธปืน - อาวุธและกระสุน',
            '李来福\tหลี่ไหลฝู']
    result = extract_new_vocabulary(novel + newline + 'คำศัพท์ใหม่' + newline + newline.join(rows))
    assert result.cleaned_text == novel
    assert result.vocabulary_text == newline.join(rows)
    assert result.vocabulary_count == 3


def test_new_unstructured_layout_is_copied_automatically():
    novel = 'บทที่ 750\nข้อความ\n[จบตอน]\n'
    block = '李来福 เดินกลับเข้าบ้าน\n(คำศัพท์อิสระ) 📖 中文 THAI'
    text = novel + 'คำศัพท์ใหม่\n' + block
    result = extract_new_vocabulary(text)
    assert result.status == 'extracted'
    assert not result.reviewable
    assert result.cleaned_text == novel
    assert result.vocabulary_text == block
    assert result.vocabulary_count == 2
    assert extract_new_vocabulary(text, allow_unstructured=True) == result


@pytest.mark.parametrize('text', [
    'บทที่ 750\nตัวละครกล่าวถึงคำศัพท์ใหม่ในประโยค\n李来福 เดินกลับบ้าน',
    'บทที่ 750\nคำศัพท์ใหม่\n李来福 เดินกลับเข้าบ้าน',
    'บทที่ 750\n[จบตอน]\nคำศัพท์ใหม่\n[-]\n李来福 - หลี่ไหลฝู',
    'บทที่ 750\n[จบตอน]\nคำศัพท์ใหม่\n李来福 - หลี่ไหลฝู\nคำศัพท์ใหม่\n来福 - ไหลฝู',
])
def test_unsafe_sections_stay_unchanged_even_when_unstructured_allowed(text):
    first = extract_new_vocabulary(text)
    reviewed = extract_new_vocabulary(text, allow_unstructured=True)
    assert first.cleaned_text == text
    assert reviewed.cleaned_text == text
    assert reviewed.status in {'ambiguous', 'none'}


@pytest.mark.parametrize('marker', ['[จบตอน]', '[จบบท]'])
@pytest.mark.parametrize('newline', ['\\n', '\\r\\n'])
def test_copy_all_rows_verbatim_like_ctrl_c(marker, newline):
    novel = newline.join(['บทที่ 750', 'เนื้อหา', marker]) + newline
    raw_rows = [
        '李来福\\tหลี่ไหลฝู\\tชาย\\tคำอธิบาย  ',
        'จีน ไทย - คำอธิบายใด ๆ',
        'plain text  with   spaces',
        ' ',
        '📘 note (เก็บไว้ตรวจภายหลัง)',
        '| term | meaning |',
        '| --- | --- |',
        '| 李来福 | หลี่ไหลฝู |',
        '李来福\\tหลี่ไหลฝู\\tชาย\\tคำอธิบาย  ',
    ]
    raw = newline.join(raw_rows)
    result = extract_new_vocabulary(novel + 'คำศัพท์ใหม่:' + newline + raw)
    assert result.status == 'extracted'
    assert result.original_text == novel + 'คำศัพท์ใหม่:' + newline + raw
    assert result.cleaned_text == novel
    assert result.vocabulary_text == raw
    assert result.vocabulary_count == 8


def test_blank_line_heading_copies_any_layout_without_end_marker():
    novel = 'บทที่ 750\\nเนื้อหา\\n'
    text = novel + '\\nคำศัพท์ใหม่\\nanything AI provides: คำศัพท์ 🪄'
    result = extract_new_vocabulary(text)
    assert result.status == 'extracted'
    assert result.cleaned_text == novel
    assert result.vocabulary_text == 'anything AI provides: คำศัพท์ 🪄'


def test_two_sections_end_at_next_chapter_without_blank_separator():
    text = ('บทที่ 750\\nเนื้อหา\\n[จบตอน]\\nคำศัพท์ใหม่\\n'
            'คัดลอกทุกคำ แม้ไม่ใช่ตาราง\\n'
            'บทที่ 751\\nเนื้อหาตอนใหม่\\n[จบบท]\\nคำศัพท์ใหม่\\n'
            'second block: 还行')
    result = extract_new_vocabulary(text)
    assert result.status == 'extracted'
    assert result.cleaned_text == ('บทที่ 750\\nเนื้อหา\\n[จบตอน]\\n'
                                   'บทที่ 751\\nเนื้อหาตอนใหม่\\n[จบบท]\\n')
    assert result.vocabulary_text == 'คัดลอกทุกคำ แม้ไม่ใช่ตาราง\\nsecond block: 还行'
    assert result.vocabulary_count == 2


def test_empty_or_mixed_sentinel_rejected_without_modification():
    for tail in ['', '\\n', '\\n[-]\\n李来福 หลี่ไหลฝู', '\\n李来福 หลี่ไหลฝู\\n[-]']:
        text = 'บทที่ 751\\n[จบบท]\\nคำศัพท์ใหม่' + tail
        result = extract_new_vocabulary(text)
        assert result.status == 'ambiguous'
        assert result.cleaned_text == result.original_text == text


def test_headings_in_prose_are_not_sections():
    text = 'บทที่ 751\\nคำศัพท์ใหม่ถือเป็นคำบอกเล่า\\nเนื้อหา'
    assert extract_new_vocabulary(text).cleaned_text == text


def test_crlf_bom_without_heading_is_byte_identical():
    text = '\\ufeffบทที่ 751\\r\\nเนื้อหา  \\r\\n[จบตอน]\\r\\n'
    result = extract_new_vocabulary(text)
    assert result.status == 'none'
    assert result.original_text == result.cleaned_text == text
