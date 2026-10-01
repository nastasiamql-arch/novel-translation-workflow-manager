import json
import os
from urllib.error import HTTPError

import pytest


def test_providers_send_contract_and_refuse_redirects(monkeypatch):
    from novel_workflow import providers
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({"choices":[{"finish_reason":"stop","message":{"content":"output"}}]}).encode()
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response()
    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    provider = providers.create_provider("openai", "https://api.openai.com/v1")
    assert provider.complete("model", "instructions", "secret") == "output"
    body = json.loads(requests[0].data)
    assert body["model"] == "model" and body["messages"][0]["content"] == "instructions"
    assert requests[0].get_header("Authorization") == "Bearer secret"
    with pytest.raises(HTTPError): providers.NoRedirect().redirect_request(requests[0], None, 302, "redirect", {}, "https://other.example")


@pytest.mark.parametrize("endpoint", ["http://api.example/v1", "https://user:secret@api.example", "https://api.example/?key=secret", "https://api.example/#secret"])
def test_unsafe_endpoints_rejected(endpoint):
    from novel_workflow.providers import create_provider
    with pytest.raises(ValueError): create_provider("openai", endpoint)


def test_provider_error_redacts_response_and_key(monkeypatch):
    from novel_workflow import providers
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("https://api.example", 401, "secret prompt", {}, None)
    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError) as error:
        providers.create_provider("openai", "https://api.example/v1").complete("m", "private prompt", "secret")
    assert "401" in str(error.value) and "secret" not in str(error.value) and "prompt" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_dpapi_key_roundtrip_and_no_plaintext(tmp_path):
    from novel_workflow.credentials import CredentialStore
    store = CredentialStore(tmp_path)
    store.set("a" * 32, "openai", "secret-api-key")
    assert store.get("a" * 32, "openai") == "secret-api-key"
    assert store.get("b" * 32, "openai") == ""
    assert all(b"secret-api-key" not in p.read_bytes() for p in tmp_path.iterdir())
    store.delete("a" * 32, "openai")
    assert store.get("a" * 32, "openai") == ""


def test_cancellation_keeps_vocab(tmp_path):
    from test_vocabulary import setup_run, api_result
    from novel_workflow.vocabulary import run_vocabulary, Cancelled
    settings, vocab = setup_run(tmp_path)
    original = vocab.read_bytes()
    stopped = []
    class Provider:
        def complete(self, *args):
            stopped.append(True)
            return api_result()
    with pytest.raises(Cancelled): run_vocabulary(settings, Provider(), "key", cancelled=lambda: bool(stopped))
    assert vocab.read_bytes() == original


def test_anthropic_payload_and_truncation(monkeypatch):
    from novel_workflow.providers import AnthropicProvider
    provider = AnthropicProvider("https://api.anthropic.com/v1")
    calls = []
    def post(route, body, headers):
        calls.append((route, body, headers))
        return {"stop_reason":"end_turn", "content":[{"type":"text", "text":"output"}]}
    monkeypatch.setattr(provider, "post", post)
    assert provider.complete("m", "prompt", "key") == "output"
    assert calls[0][0] == "/messages" and calls[0][1]["max_tokens"] == 8192
    assert calls[0][2]["x-api-key"] == "key"
    monkeypatch.setattr(provider, "post", lambda *args: {"stop_reason":"max_tokens", "content":[]})
    with pytest.raises(ValueError, match="incomplete"): provider.complete("m", "prompt", "key")


def test_openai_rejects_truncated_content(monkeypatch):
    from novel_workflow.providers import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider("https://api.example/v1")
    monkeypatch.setattr(provider, "post", lambda *args: {"choices":[{"finish_reason":"length","message":{"content":"{}"}}]})
    with pytest.raises(ValueError, match="incomplete"): provider.complete("m", "p", "k")


def test_model_discovery_uses_models_route_and_bearer_key(monkeypatch):
    from novel_workflow import providers
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"data":[{"id":"alpha"},{"id":"beta"},{"id":"alpha"}]}'
    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout)); return Response()
    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    provider = providers.create_provider("openai-compatible", "https://api.maxplus-ai.cc/v1")
    assert provider.list_models("secret") == ["alpha", "beta"]
    assert requests[0][0].full_url == "https://api.maxplus-ai.cc/v1/models"
    assert requests[0][0].get_header("Authorization") == "Bearer secret"
    assert requests[0][1] == 30


def test_model_discovery_rejects_empty_and_sanitizes_http_error(monkeypatch):
    from novel_workflow import providers
    provider = providers.create_provider("openai-compatible", "https://api.example/v1")
    monkeypatch.setattr(provider, "get", lambda *args: {"data": []})
    with pytest.raises(ValueError, match="No models"):
        provider.list_models("key")
    monkeypatch.undo()
    class Opener:
        def open(self, *args, **kwargs): raise HTTPError("https://api.example", 401, "private key body", {}, None)
    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError) as error: provider.list_models("key")
    assert "401" in str(error.value) and "private" not in str(error.value)


def test_anthropic_model_discovery_auth_headers(monkeypatch):
    from novel_workflow.providers import AnthropicProvider
    provider = AnthropicProvider("https://api.anthropic.com/v1")
    calls = []
    monkeypatch.setattr(provider, "get", lambda route, headers: calls.append((route, headers)) or {"data":[{"id":"claude"}]})
    assert provider.list_models("secret") == ["claude"]
    assert calls[0][0] == "/models"
    assert calls[0][1]["x-api-key"] == "secret"


def test_maxplus_root_url_discovers_pool_from_key_scope(monkeypatch):
    from novel_workflow.providers import OpenAICompatibleProvider, connect_and_list_models
    attempted = []
    def list_models(self, key):
        attempted.append(self.base_url)
        if self.base_url.endswith("/gemini-full/v1"):
            return ["gemini-3.8-flash"]
        raise ValueError("Provider HTTP 403; check key and API access")
    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", list_models)
    provider = OpenAICompatibleProvider("https://api.maxplus-ai.cc")
    endpoint, models = connect_and_list_models(provider, "private-key")
    assert endpoint == "https://api.maxplus-ai.cc/gemini-full/v1"
    assert models == ["gemini-3.8-flash"]
    assert attempted == ["https://api.maxplus-ai.cc/gemini-full/v1"]


def test_maxplus_discovery_preserves_explicit_pool_url(monkeypatch):
    from novel_workflow.providers import OpenAICompatibleProvider, connect_and_list_models
    calls = []
    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", lambda self, key: calls.append(self.base_url) or ["m"])
    provider = OpenAICompatibleProvider("https://api.maxplus-ai.cc/gemini-full/v1")
    assert connect_and_list_models(provider, "key") == (provider.base_url, ["m"])
    assert calls == [provider.base_url]


def test_maxplus_discovery_checks_other_openai_compatible_pools(monkeypatch):
    from novel_workflow.providers import OpenAICompatibleProvider, connect_and_list_models
    calls = []
    def list_models(self, key):
        calls.append(self.base_url)
        if self.base_url.endswith("/gpt-pro/v1"): return ["gpt-model"]
        raise ValueError("Provider HTTP 403; check key and API access")
    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", list_models)
    endpoint, models = connect_and_list_models(OpenAICompatibleProvider("https://api.maxplus-ai.cc"), "key")
    assert endpoint.endswith("/gpt-pro/v1")
    assert models == ["gpt-model"]
    assert len(calls) > 1


def test_maxplus_discovery_uses_anthropic_pool_routes_for_anthropic_provider(monkeypatch):
    from novel_workflow.providers import AnthropicProvider, connect_and_list_models
    calls = []
    def list_models(self, key):
        calls.append(self.base_url)
        if self.base_url.endswith("/cmax-full/v1"): return ["claude-model"]
        raise ValueError("Provider HTTP 403; check key and API access")
    monkeypatch.setattr(AnthropicProvider, "list_models", list_models)
    endpoint, models = connect_and_list_models(AnthropicProvider("https://api.maxplus-ai.cc"), "key")
    assert endpoint.endswith("/cmax-full/v1")
    assert models == ["claude-model"]
