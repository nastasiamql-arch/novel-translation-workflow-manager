import pytest

from novel_workflow.downloader.registry import SourceRegistry
from novel_workflow.downloader.sources.tomatomtl import TomatoMTLSource


def test_tomatomtl_url_matching_and_book_id():
    registry = SourceRegistry([TomatoMTLSource(client=object())])
    source = registry.match("https://tomatomtl.com/book/7505707616878742553")
    assert source.id == "tomatomtl"
    assert source.extract_book_id("https://www.tomatomtl.com/book/123?x=1") == "123"


def test_unknown_source_error_is_clear():
    with pytest.raises(ValueError, match="No supported source"):
        SourceRegistry([TomatoMTLSource(client=object())]).match("https://example.org/book/1")
