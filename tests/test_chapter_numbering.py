import pytest

from novel_workflow.chapter_numbering import (
    chapter_issues, duplicate_heading_removal_plan, parse_number,
    preview_renumber, scan_chapters,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("559", 559), ("５５９", 559), ("五百五十九", 559),
    ("四百三十", 430), ("十", 10), ("两千零五", 2005),
    ("一万零二", 10002),
])
def test_chinese_numbers(raw, expected):
    assert parse_number(raw) == expected


def test_scan_original_chinese_and_preserve_story():
    text = ("第538章 中计\n張巖身上有559枚靈石。\n"
            "第559章 魂归火炬\n这里是第560章的故事，不是标题。\n"
            "第560章 血龙之威\n")
    found = scan_chapters(text)
    assert [x.number for x in found] == [538, 559, 560]
    assert chapter_issues(found) == ["ปกติ", "เลขกระโดด / อาจมีบทขาดจริง", "ปกติ"]
    result, changes = preview_renumber(text, {1: 539, 2: 540})
    assert changes == [(3, 559, 539), (5, 560, 540)]
    assert result == text.replace("第559章 魂归火炬", "第539章 魂归火炬").replace(
        "第560章 血龙之威", "第540章 血龙之威"
    )
    assert "張巖身上有559枚靈石" in result


def test_one_chapter_fate_sample_does_not_change():
    text = "第430章 大結局\n　　日上三竿，陽光穿過窗簾。\n　　（全書完）"
    assert [x.number for x in scan_chapters(text)] == [430]
    assert chapter_issues(scan_chapters(text)) == ["ปกติ"]
    assert preview_renumber(text, {}) == (text, [])


def test_overlap_and_duplicate_not_silent():
    text = "第538章 中计\n正文\n第559章 魂归火炬\n第二章内容\n"
    with pytest.raises(ValueError, match="collide"):
        preview_renumber(text, {1: 538})
    assert preview_renumber(text, {1: 539})[0].count("正文") == 1


def test_old_chapter_and_out_of_order_are_only_flagged():
    headings = scan_chapters("第538章\n内容\n第520章\n内容\n第538章\n内容")
    assert chapter_issues(headings) == ["ปกติ", "เลขย้อนกลับ", "เลขซ้ำ"]


def test_multi_language_and_fenced_examples():
    txt = ("Chapter 10: Title\nbody\nบทที่ 11 เนื้อหา\n"
           "ตอนที่ 12 เรื่อง\n\x60\x60\x60text\n第900章 示例\n\x60\x60\x60\n第十三章 標題\n")
    assert [h.number for h in scan_chapters(txt)] == [10, 11, 12, 13]


@pytest.mark.parametrize(("heading", "title"), [
    ("第25章月薪40万", "月薪40万"),
    ("第25章 月薪40万", "月薪40万"),
    ("第25章　月薪40万", "月薪40万"),
    ("第二十五章月薪40万", "月薪40万"),
    ("第２５章月薪40万", "月薪40万"),
])
def test_chinese_heading_titles_can_touch_zhang(heading, title):
    found = scan_chapters(heading + "\n正文\n")
    assert len(found) == 1
    assert found[0].number == 25
    assert found[0].title == title


def test_duplicate_heading_classification_requires_same_title_and_no_story_between():
    duplicate = "第25章月薪40万\n第25章 月薪40万\n"
    headings = scan_chapters(duplicate)
    assert chapter_issues(headings, duplicate) == [
        "ปกติ", "หัวบทซ้ำที่น่าจะเป็นรายการเดียวกัน"
    ]

    different_title = "第25章月薪40万\n第25章 新的交易\n"
    assert chapter_issues(scan_chapters(different_title), different_title)[1] == (
        "เลขบทซ้ำ แต่ชื่อบทต่างกัน"
    )

    with_story = "第25章月薪40万\n\nเนื้อเรื่อง\n第25章 月薪40万\n"
    assert chapter_issues(scan_chapters(with_story), with_story)[1] == (
        "เลข/ชื่อบทซ้ำ แต่มีเนื้อหาคั่น · ตรวจเนื้อเรื่อง"
    )


def test_duplicate_heading_removal_plan_only_removes_safe_duplicate_header_lines():
    text = "第25章月薪40万\n第25章 月薪40万\n正文仍อยู่ครบ\n第25章 新的交易\n"
    planned, removed = duplicate_heading_removal_plan(text)
    assert removed == [2]
    assert planned == "第25章月薪40万\n正文仍อยู่ครบ\n第25章 新的交易\n"

    with_story = "第25章 月薪40万\nเนื้อเรื่อง\n第25章月薪40万\n"
    assert duplicate_heading_removal_plan(with_story) == (with_story, [])

    different_title = "第25章 月薪40万\n第25章 新的交易\n"
    assert duplicate_heading_removal_plan(different_title) == (different_title, [])


def test_narrative_sentence_starting_with_chapter_number_is_not_a_heading():
    text = "第25章的故事在这一刻才刚刚开始。\n第26章真正的标题\n"
    assert [heading.number for heading in scan_chapters(text)] == [26]


def test_invalid_or_unrecognized_are_not_modified():
    text = "第0章 Invalid\n第???章 Name\n这个故事有第559章的说法。\n"
    assert scan_chapters(text) == []
    assert preview_renumber(text, {}) == (text, [])
