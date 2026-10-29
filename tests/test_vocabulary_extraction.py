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
