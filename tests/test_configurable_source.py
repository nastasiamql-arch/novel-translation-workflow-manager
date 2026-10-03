import json

import pytest

from novel_workflow.downloader.sources.configurable import ConfigurableSource, load_configurable_sources


CONFIG = {
    "id": "example_novel", "name": "Example Novel", "domains": ["novel.example.com"],
    "book": {"title": "h1.title", "author": ".author", "chapters": ".chapter-list a"},
    "chapter": {"title": "h1.chapter-title", "content": ".chapter-content", "remove": [".ads"]},
}


def test_config_validation_does_not_execute_code():
    source = ConfigurableSource(CONFIG)
    assert source.id == "example_novel"
    with pytest.raises(ValueError, match="selectors require"):
        ConfigurableSource({**CONFIG, "chapter": {"content": ".body"}})


def test_load_sources_reports_bad_json_without_blocking_valid(tmp_path):
    (tmp_path / "valid.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (tmp_path / "invalid.json").write_text("{", encoding="utf-8")
    errors = []
    loaded = load_configurable_sources(tmp_path, errors=errors)
    assert [item.id for item in loaded] == ["example_novel"]
    assert errors and "invalid.json" in errors[0]


def test_duplicate_custom_ids_are_reported_without_breaking_registry(tmp_path):
    from novel_workflow.downloader.registry import SourceRegistry
    duplicate = {**CONFIG, "domains": ["other.example.com"]}
    (tmp_path / "one.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (tmp_path / "two.json").write_text(json.dumps(duplicate), encoding="utf-8")
    registry = SourceRegistry.builtins(tmp_path)
    assert [source.id for source in registry.list_sources()] == ["tomatomtl", "example_novel"]
    assert any("already registered" in error for error in registry.load_errors)
