import time
import threading

import httpx


class HttpClient:
    def __init__(self, *, timeout=20.0, min_interval=1.0, retries=2, user_agent="PalantirNovel/2.4.0"):
        self.client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent, "Accept": "text/html,application/json"})
        self.min_interval = min_interval
        self.retries = retries
        self._last_request = 0.0
        self._lock = threading.Lock()
        self.cancel_event = None

    def get(self, url, *, cancel=None):
        cancel = cancel or self.cancel_event
        for attempt in range(self.retries + 1):
            if cancel and cancel.is_set():
                raise InterruptedError("Download cancelled")
            with self._lock:
                delay = self.min_interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    if cancel and cancel.wait(delay):
                        raise InterruptedError("Download cancelled")
                    if not cancel:
                        time.sleep(delay)
                self._last_request = time.monotonic()
            try:
                response = self.client.get(url)
                if response.status_code in (408, 425, 429, 500, 502, 503, 504) and attempt < self.retries:
                    self._backoff(0.75 * (2 ** attempt), cancel)
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.retries:
                    raise RuntimeError(f"Could not reach source: {exc}") from exc
                self._backoff(0.75 * (2 ** attempt), cancel)
        raise RuntimeError("Request failed")

    @staticmethod
    def _backoff(delay, cancel):
        delay = min(8, delay)
        if cancel:
            if cancel.wait(delay): raise InterruptedError("Download cancelled")
        else:
            time.sleep(delay)

    def close(self):
        self.client.close()
