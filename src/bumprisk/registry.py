"""Read-only lookups against public registries (npm, PyPI) and OSV.dev.

All network access goes through one `Http` object so tests can swap it for a fake.
Nothing is ever uploaded except package names and versions (to OSV).
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

UA = f"bumprisk/{__version__} (+https://github.com/hamarshehmhmd/bumprisk)"


class NotFound(Exception):
    pass


class LookupFailed(Exception):
    pass


class Http:
    def __init__(self, timeout: float = 30.0, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._cache: dict = {}
        self._lock = threading.Lock()

    def get_json(self, url: str, headers: dict | None = None):
        return self._request("GET", url, None, headers)

    def post_json(self, url: str, body):
        return self._request("POST", url, json.dumps(body).encode(), {"Content-Type": "application/json"})

    def _request(self, method, url, data, headers):
        key = (method, url, data)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        h = {"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "application/json"}
        h.update(headers or {})
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    val = json.loads(raw)
                    with self._lock:
                        self._cache[key] = val
                    return val
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    raise NotFound(url) from e
                last = f"HTTP {e.code}"
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = str(e)
            time.sleep(0.5 * (attempt + 1))
        raise LookupFailed(f"{url}: {last}")


def npm_registry() -> str:
    return (os.environ.get("BUMPRISK_NPM_REGISTRY") or "https://registry.npmjs.org").rstrip("/")


def pypi_index() -> str:
    return (os.environ.get("BUMPRISK_PYPI_URL") or "https://pypi.org").rstrip("/")


class Registries:
    def __init__(self, http: Http | None = None):
        self.http = http or Http()

    # npm -----------------------------------------------------------------
    def npm_packument(self, name: str) -> dict:
        return self.http.get_json(f"{npm_registry()}/{urllib.parse.quote(name, safe='@')}")

    def npm_weekly_downloads(self, name: str):
        try:
            d = self.http.get_json(f"https://api.npmjs.org/downloads/point/last-week/{name}")
            return d.get("downloads")
        except (NotFound, LookupFailed):
            return None

    # PyPI ----------------------------------------------------------------
    def pypi_project(self, name: str) -> dict:
        return self.http.get_json(f"{pypi_index()}/pypi/{name}/json")

    def pypi_simple(self, name: str) -> dict:
        return self.http.get_json(f"{pypi_index()}/simple/{name}/",
                                  {"Accept": "application/vnd.pypi.simple.v1+json"})

    # OSV -----------------------------------------------------------------
    def osv_batch(self, queries: list) -> list:
        """queries: [(ecosystem, name, version)] -> [list of vuln ids] (same order)."""
        out = []
        for i in range(0, len(queries), 500):
            chunk = queries[i:i + 500]
            body = {"queries": [{"package": {"ecosystem": e, "name": n}, "version": v} for e, n, v in chunk]}
            res = self.http.post_json("https://api.osv.dev/v1/querybatch", body)
            for r in res.get("results", []):
                out.append([v["id"] for v in r.get("vulns", []) or []])
        return out

    def osv_vuln(self, vid: str) -> dict:
        return self.http.get_json(f"https://api.osv.dev/v1/vulns/{vid}")
