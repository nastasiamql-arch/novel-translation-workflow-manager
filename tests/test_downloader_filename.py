from novel_workflow.downloader.filename import format_chapter_filename


def test_chapter_padding_and_unicode():
    assert format_chapter_filename(1, "第一章") == "0001 第一章.txt"
    assert format_chapter_filename(10000, "终章") == "10000 终章.txt"


def test_invalid_windows_characters_keep_full_width_punctuation():
    assert format_chapter_filename(12, "第12章 / 谁:赢？") == "0012 第12章 _ 谁_赢？.txt"


def test_reserved_empty_and_long_names():
    assert format_chapter_filename(2, "CON").startswith("0002 _CON")
    assert format_chapter_filename(3, "   ") == "0003 untitled.txt"
    name = format_chapter_filename(4, "中" * 500)
    assert len(name) <= 180 and name.startswith("0004 ") and name.endswith(".txt")
