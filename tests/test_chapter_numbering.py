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


@pytest.mark.parametrize("prefix", ["　", "　　", "　 \t", "\t　"])
def test_ideographic_indentation_before_chinese_chapter(prefix):
    text = f"{prefix}第2章分割遗产\n　　正文\n{prefix}第3章下一个章节\n"
    headings = scan_chapters(text)
    assert [heading.number for heading in headings] == [2, 3]
    assert headings[0].title == "分割遗产"
    assert chapter_issues(headings, text) == ["ปกติ", "ปกติ"]
    result, changes = preview_renumber(text, {0: 5, 1: 6})
    assert changes == [(1, 2, 5), (3, 3, 6)]
    assert result == text.replace("第2章", "第5章").replace("第3章", "第6章")
    assert result.startswith(prefix)


def test_explicit_chinese_volumes_reset_duplicate_and_gap_detection():
    from novel_workflow.chapter_numbering import chapter_groups
    text = (
        "第一卷 起点\n第99章 旧事\n第100章 终章\n"
        "　　第二卷 新的开始\n　　第1章分割遗产\n　第2章 后续\n"
        "第三卷\n第1章新篇\n"
    )
    found = scan_chapters(text)
    assert [h.number for h in found] == [99, 100, 1, 2, 1]
    assert [h.volume for h in found] == [1, 1, 2, 2, 3]
    assert chapter_groups(found) == [0, 0, 1, 1, 2]
    assert chapter_issues(found, text) == ["ปกติ"] * 5
    # Repeated local chapter numbers in distinct volumes are not collisions.
    changed, rows = preview_renumber(text, {3: 3})
    assert len(rows) == 1 and "第3章 后续" in changed
    with pytest.raises(ValueError, match="collide"):
        preview_renumber(text, {3: 1})


def test_unlabelled_rollback_remains_warning_until_volume_confirmed():
    from novel_workflow.chapter_numbering import chapter_groups
    text = "第99章\n第100章\n第1章 新卷\n第2章 分割遗产\n"
    found = scan_chapters(text)
    assert chapter_issues(found, text) == ["ปกติ", "ปกติ", "เลขย้อนกลับ", "ปกติ"]
    assert chapter_groups(found, {2}) == [0, 0, 1, 1]
    assert chapter_issues(found, text, {2}) == ["ปกติ"] * 4
    with pytest.raises(ValueError, match="collide"):
        preview_renumber(text, {1: 99})
    result, changes = preview_renumber(text, {0: 1}, {2})
    assert changes == [(1, 99, 1)]
    assert result.startswith("第1章")
    # No deletion across a confirmed volume boundary even with equal titles.
    duplicate = "第1章 同题\n第1章 同题\n"
    assert duplicate_heading_removal_plan(duplicate, {1}) == (duplicate, [])


def test_indented_unrecognized_chapter_is_not_silently_renumbered():
    from novel_workflow.chapter_numbering import automatic_renumber_plan
    with pytest.raises(ValueError, match="อ่านเลขไม่ได้"):
        automatic_renumber_plan("　　第1章 第一个\n　　第???章 错误\n", 10)
    with pytest.raises(ValueError, match="หลายเล่ม"):
        automatic_renumber_plan("第一卷\n第1章\n第二卷\n第1章\n", 10)


def test_fullwidth_indented_narrative_reference_is_not_a_chapter_candidate():
    from novel_workflow.chapter_numbering import automatic_renumber_plan
    text = "第六百四十一章 逆神教老巢\n正文\n第六百四十二章 余波\n　　第三章的文字不应算作章节。\n"
    result, edits = automatic_renumber_plan(text, 621)
    assert [h.number for h in scan_chapters(text)] == [641, 642]
    assert len(edits) == 2
    assert "　　第三章的文字不应算作章节。" in result
