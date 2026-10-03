import httpx
import pytest

from novel_workflow.downloader.http_client import HttpClient, SourceRateLimitError


def test_http_429_stops_immediately_instead_of_retrying():
    class Client:
        calls = 0

        def get(self, url):
            self.calls += 1
            request = httpx.Request("GET", url)
            return httpx.Response(429, request=request)

        def close(self):
            pass

    client = HttpClient(retries=3)
    fake = Client()
    client.client = fake
    try:
        with pytest.raises(SourceRateLimitError, match="rate limit"):
            client.get("https://example.test/chapter")
        assert fake.calls == 1
    finally:
        client.close()
