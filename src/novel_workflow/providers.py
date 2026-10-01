"""Small provider boundary; no SDK or API keys in persisted configuration."""
from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class Provider(Protocol):
    def complete(self, model: str, prompt: str, key: str) -> str: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Provider redirects are disabled", headers, fp)


def validate_endpoint(base_url):
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Provider URL must be HTTPS without credentials, query or fragment")
    return base_url.rstrip('/')


class HttpProvider:
    def __init__(self, base_url):
        self.base_url = validate_endpoint(base_url)

    def post(self, route, body, headers):
        request = Request(self.base_url + route, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with build_opener(NoRedirect()).open(request, timeout=60) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000: raise ValueError("Provider response exceeds limit")
            return json.loads(raw)
        except HTTPError as error:
            raise ValueError(f"Provider HTTP {error.code}; check key, model and quota") from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("Provider connection failed or timed out") from None
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("Provider returned invalid JSON") from None

    def get(self, route, headers):
        request = Request(self.base_url + route, headers=headers, method="GET")
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000: raise ValueError("Provider response exceeds limit")
            return json.loads(raw)
        except HTTPError as error:
            raise ValueError(f"Provider HTTP {error.code}; check key and API access") from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("Provider connection failed or timed out") from None
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("Provider returned invalid JSON") from None

    def list_models(self, key, headers):
        self.validate_request("model-list", key)
        response = self.get("/models", headers)
        try:
            entries = response["data"]
            if not isinstance(entries, list): raise TypeError
            models, seen = [], set()
            for entry in entries:
                model = entry.get("id") if isinstance(entry, dict) else None
                if isinstance(model, str) and model.strip() and not any(ord(c) < 32 for c in model) and model not in seen:
                    seen.add(model)
                    models.append(model)
                    if len(models) >= 2000: break
            if not models: raise ValueError("No models available for this API key")
            return models
        except (KeyError, TypeError): raise ValueError("Provider returned an unexpected model list") from None

    @staticmethod
    def validate_request(model, key):
        if not model.strip(): raise ValueError("Choose a model first")
        if not key.strip() or any(c in key for c in '\r\n'): raise ValueError("Configure a valid API key first")


class OpenAICompatibleProvider(HttpProvider):
    def list_models(self, key):
        return super().list_models(key, {"Authorization": "Bearer " + key})

    def complete(self, model, prompt, key):
        self.validate_request(model, key)
        response = self.post("/chat/completions", {"model": model,
            "messages": [{"role": "user", "content": prompt}]}, {"Authorization": "Bearer " + key})
        try:
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop": raise ValueError("Provider response is incomplete or refused")
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip(): raise ValueError("Provider returned empty content")
            return text
        except (KeyError, IndexError, TypeError): raise ValueError("Unexpected provider response") from None


class AnthropicProvider(HttpProvider):
    def list_models(self, key):
        return super().list_models(key, {"x-api-key": key, "anthropic-version": "2023-06-01"})

    def complete(self, model, prompt, key):
        self.validate_request(model, key)
        response = self.post("/messages", {"model": model, "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}]},
            {"x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            if response.get("stop_reason") != "end_turn": raise ValueError("Provider response is incomplete or refused")
            text = ''.join(item["text"] for item in response["content"] if item.get("type") == "text")
            if not text.strip(): raise ValueError("Provider returned empty content")
            return text
        except (KeyError, TypeError): raise ValueError("Unexpected provider response") from None


def create_provider(provider, base_url):
    if provider in {"openai", "openai-compatible"}: return OpenAICompatibleProvider(base_url)
    if provider == "anthropic": return AnthropicProvider(base_url)
    raise ValueError("Unknown API provider")


MAXPLUS_OPENAI_POOL_PATHS = (
    # Gemini Full is the route shown for the user's key in the MaxPlus dashboard.
    "/gemini-full/v1", "/gemini/v1", "/gemini-lite/v1", "/gemini-stable/v1", "/v1",
    "/maxpools/v1", "/mirrorpools/v1", "/vip-pools/v1", "/claude-vertex/v1",
    "/deepseek/v1", "/chinese-model-specials/v1", "/all-max-pools/v1",
    "/chinese-model-request/v1", "/chinese-request-specials/v1", "/glm/v1", "/glm-free/v1",
    "/glm-deepseek-cheaper/v1", "/free/v1", "/kimi/v1", "/minimax/v1", "/gpt-pro/v1",
    "/gpt-plus-pro/v1", "/gpt-pro-20x-ultimate/v1", "/gpt-pro-20x-stable/v1", "/gpt-max/v1",
    "/gpt-lite/v1", "/gpt-bomb/v1", "/grok/v1", "/grok-fast/v1", "/grok-lite/v1", "/super-grok/v1",
)
MAXPLUS_ANTHROPIC_POOL_PATHS = (
    "/v1", "/maxpools/v1", "/subpools/v1", "/claude-aws/v1", "/kiro-high-cache/v1",
    "/aws-v2/v1", "/aws-lite/v1", "/ccmax/v1", "/aws-lite-ultimate/v1", "/claudecode-lite/v1",
    "/cmax-lite/v1", "/cmax-full/v1", "/cmax-specials/v1", "/claude-kiro-faster/v1",
    "/claude-kiro-pure/v1", "/claude-cursor/v1", "/claude-antigravity/v1", "/kiro-p-90/v1",
    "/kiro-coperate/v1", "/kiro-95-cache/v1", "/kiro-99-cache/v1", "/kiro-90-cache/v1",
    "/kiro-70-cache/v1", "/kiro-p-92/v1", "/kiro-p-99/v1", "/claude-cc/v1",
    "/claude-github-copilot/v1", "/claude-vertex/v1", "/cowork/v1", "/mirrorpools/v1", "/vip-pools/v1",
)


def connect_and_list_models(provider, key):
    """Resolve a MaxPlus pool from a key when only the API origin was entered."""
    parsed = urlsplit(provider.base_url)
    is_maxplus_origin = (type(provider) in {OpenAICompatibleProvider, AnthropicProvider}
                         and parsed.hostname == "api.maxplus-ai.cc" and parsed.path in {"", "/"})
    if not is_maxplus_origin:
        return provider.base_url, provider.list_models(key)

    # A MaxPlus API key is authorized for its pool, while the API root defaults
    # to Native. Probe documented pool model-list routes on the same HTTPS host.
    # These GET requests send only the key; no prompt or file content is sent.
    pool_paths = MAXPLUS_ANTHROPIC_POOL_PATHS if isinstance(provider, AnthropicProvider) else MAXPLUS_OPENAI_POOL_PATHS
    last_error = None
    temporary_server_error = None
    temporary_server_message = None
    for path in pool_paths:
        candidate = type(provider)(f"{parsed.scheme}://{parsed.netloc}{path}")
        try:
            return candidate.base_url, candidate.list_models(key)
        except ValueError as error:
            message = str(error)
            if "Provider HTTP 403" in message or "Provider HTTP 404" in message:
                last_error = error
                continue
            # A pool can be temporarily unavailable while another pool is
            # healthy. Keep probing; if none work, report the outage accurately.
            if any(f"Provider HTTP {code}" in message for code in (500, 502, 503, 504)):
                temporary_server_error = error
                temporary_server_message = message.split(";", 1)[0]
                continue
            raise
    if temporary_server_error:
        raise ValueError(f"{temporary_server_message}; MaxPlus API/Pool is temporarily unavailable; retry later") from None
    raise ValueError("Could not find a compatible MaxPlus Gemini pool for this key") from last_error
