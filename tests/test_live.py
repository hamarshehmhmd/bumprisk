"""Live checks against the real npm registry, PyPI and OSV.dev (opt-in: BUMPRISK_LIVE=1)."""
import json
import os

import pytest

from bumprisk import cli

pytestmark = pytest.mark.skipif(not os.environ.get("BUMPRISK_LIVE"), reason="set BUMPRISK_LIVE=1")
EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def run(capsys, kind):
    rc = cli.main(["compare", f"{EX}/{kind}/old/{'package-lock.json' if kind == 'npm' else 'requirements.txt'}",
                   f"{EX}/{kind}/new/{'package-lock.json' if kind == 'npm' else 'requirements.txt'}",
                   "--format", "json"])
    return rc, {c["name"]: c for c in json.loads(capsys.readouterr().out)["changes"]}


def test_live_npm_incidents(capsys):
    rc, by = run(capsys, "npm")
    assert rc == 1
    assert by["plain-crypto-js"]["severity"] == "critical"
    assert "unpublished" in {f["code"] for f in by["axios"]["findings"]}
    assert "malware" in {f["code"] for f in by["chalk"]["findings"]}


def test_live_pypi_incidents(capsys):
    rc, by = run(capsys, "python")
    assert rc == 1
    assert "yanked" in {f["code"] for f in by["requests"]["findings"]}
    assert "not-found" in {f["code"] for f in by["ultralytics"]["findings"]}
