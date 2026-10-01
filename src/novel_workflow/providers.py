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

    @staticmethod
    def validate_request(model, key):
        if not model.strip(): raise ValueError("Choose a model first")
        if not key.strip() or any(c in key for c in '\r\n'): raise ValueError("Configure a valid API key first")


class OpenAICompatibleProvider(HttpProvider):
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
