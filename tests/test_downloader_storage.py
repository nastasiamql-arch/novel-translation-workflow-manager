import json

from novel_workflow.downloader.models import DownloaderBook, DownloaderSourceBinding
from novel_workflow.downloader.storage import DownloaderRepository, downloader_data_root


def test_downloader_root_uses_its_own_namespace(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert downloader_data_root() == tmp_path / "NovelDownloader"
    assert downloader_data_root() != tmp_path / "NovelWorkflow"


def test_library_round_trips_without_main_profile_storage(tmp_path):
    root = tmp_path / "NovelDownloader"
    repository = DownloaderRepository(root)
    book = DownloaderBook(title="原文 Novel", source_binding=DownloaderSourceBinding(
        "tomatomtl", "https://tomatomtl.com/book/123", "123"),
        output_dir=str(tmp_path / "out" / "原文 Novel"))

    repository.save_book(book)
    loaded = DownloaderRepository(root).get_book(book.id)

    assert loaded.title == book.title
    assert loaded.source_binding.remote_book_id == "123"
    assert loaded.output_dir == book.output_dir
    assert json.loads(repository.books_path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_each_book_has_isolated_manifest_and_output_folder(tmp_path):
    repository = DownloaderRepository(tmp_path / "appdata")
    first = DownloaderBook(title="同名", output_dir=str(tmp_path / "out" / "同名"))
    repository.save_book(first)
    second = DownloaderBook(title="同名", output_dir=str(repository.output_path(
        "b" * 32, "同名", tmp_path / "out")))
    repository.save_book(second)

    assert first.output_dir != second.output_dir
    assert repository.manifest_path(first.id) != repository.manifest_path(second.id)


def test_storage_does_not_touch_unrelated_palantir_root(tmp_path):
    main_root = tmp_path / "NovelWorkflow"
    main_root.mkdir()
    sentinel = main_root / "profiles" / "keep.json"
    sentinel.parent.mkdir()
    sentinel.write_text('{"profile":"untouched"}', encoding="utf-8")
    repository = DownloaderRepository(tmp_path / "NovelDownloader")
    repository.save_book(DownloaderBook(title="Standalone"))

    assert json.loads(sentinel.read_text(encoding="utf-8")) == {"profile": "untouched"}
    assert not (main_root / "profiles" / "Standalone").exists()
