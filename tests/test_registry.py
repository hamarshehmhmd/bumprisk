import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bumprisk import registry
from bumprisk.registry import Http, LookupFailed, NotFound, Registries

HITS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, gz=False):
        raw = json.dumps(body).encode()
        if gz:
            raw = gzip.compress(raw)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        HITS.append((self.path, self.headers.get("Accept"), self.headers.get("User-Agent")))
        if self.path.startswith("/missing"):
            return self._send(404, {"error": "not found"})
        if self.path.startswith("/flaky") and sum(1 for p, *_ in HITS if p == self.path) == 1:
            return self._send(503, {})
        if self.path.startswith("/broken"):
            return self._send(500, {})
        if self.path.startswith("/denied"):
            return self._send(403, {})
        return self._send(200, {"path": self.path}, gz=self.path.startswith("/gz"))

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(n))
        HITS.append((self.path, body, None))
        self._send(200, {"results": [{"vulns": [{"id": "GHSA-x"}]} if q["package"]["name"] == "bad" else {}
                                     for q in body["queries"]]})


@pytest.fixture(scope="module")
def server():
    s = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_get_gzip_and_cache(server):
    h = Http(timeout=5, retries=0)
    assert h.get_json(server + "/gz/a") == {"path": "/gz/a"}
    n = len(HITS)
    assert h.get_json(server + "/gz/a") == {"path": "/gz/a"}
    assert len(HITS) == n  # cached
    assert HITS[-1][2].startswith("bumprisk/")


def test_404_is_not_found(server):
    with pytest.raises(NotFound):
        Http(timeout=5, retries=0).get_json(server + "/missing/x")


def test_retry_then_success(server, monkeypatch):
    monkeypatch.setattr(registry.time, "sleep", lambda s: None)
    assert Http(timeout=5, retries=2).get_json(server + "/flaky/1") == {"path": "/flaky/1"}


def test_persistent_5xx_and_4xx_fail(server, monkeypatch):
    monkeypatch.setattr(registry.time, "sleep", lambda s: None)
    with pytest.raises(LookupFailed, match="HTTP 500"):
        Http(timeout=5, retries=1).get_json(server + "/broken")
    with pytest.raises(LookupFailed, match="HTTP 403"):
        Http(timeout=5, retries=3).get_json(server + "/denied")


def test_connection_error_is_lookup_failed(monkeypatch):
    monkeypatch.setattr(registry.time, "sleep", lambda s: None)
    with pytest.raises(LookupFailed):
        Http(timeout=1, retries=0).get_json("http://127.0.0.1:9/nothing")


def test_registry_urls(server, monkeypatch):
    monkeypatch.setenv("BUMPRISK_NPM_REGISTRY", server + "/npm/")
    monkeypatch.setenv("BUMPRISK_PYPI_URL", server + "/pypi")
    r = Registries(Http(timeout=5, retries=0))
    assert r.npm_packument("@scope/pkg") == {"path": "/npm/@scope%2Fpkg"}
    assert r.pypi_project("requests") == {"path": "/pypi/pypi/requests/json"}
    assert r.pypi_simple("requests") == {"path": "/pypi/simple/requests/"}
    assert HITS[-1][1] == "application/vnd.pypi.simple.v1+json"


def test_osv_batch_posts_queries(server, monkeypatch):
    r = Registries(Http(timeout=5, retries=0))
    monkeypatch.setattr(r.http, "post_json",
                        lambda url, body: Http(timeout=5, retries=0).post_json(server + "/osv", body))
    assert r.osv_batch([("npm", "ok", "1.0.0"), ("PyPI", "bad", "2.0")]) == [[], ["GHSA-x"]]
    assert HITS[-1][1]["queries"][1] == {"package": {"ecosystem": "PyPI", "name": "bad"}, "version": "2.0"}
