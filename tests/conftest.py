from datetime import datetime, timezone

import pytest

from bumprisk.registry import NotFound

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def npm_version(user="alice", scripts=None, attest=False, deprecated=None, gypfile=False):
    m = {"_npmUser": {"name": user}, "scripts": scripts or {"test": "jest"}, "dist": {}}
    if attest:
        m["dist"]["attestations"] = {"url": "https://registry.npmjs.org/-/npm/v1/attestations/x", "provenance": {}}
    if deprecated:
        m["deprecated"] = deprecated
    if gypfile:
        m["gypfile"] = True
    return m


def pypi_file(kind="bdist_wheel", when="2026-01-01T00:00:00Z", yanked=False, reason=None):
    return {"packagetype": kind, "upload_time_iso_8601": when, "yanked": yanked, "yanked_reason": reason}


class FakeRegistries:
    def __init__(self, npm=None, pypi=None, simple=None, osv=None, downloads=None):
        self.npm, self.pypi, self.simple = npm or {}, pypi or {}, simple or {}
        self.osv = osv or {}
        self.downloads = downloads or {}
        self.osv_calls = []

    def npm_packument(self, name):
        if name not in self.npm:
            raise NotFound(name)
        return self.npm[name]

    def npm_weekly_downloads(self, name):
        return self.downloads.get(name, 50000)

    def pypi_project(self, name):
        if name not in self.pypi:
            raise NotFound(name)
        return self.pypi[name]

    def pypi_simple(self, name):
        if name not in self.simple:
            raise NotFound(name)
        return self.simple[name]

    def osv_batch(self, queries):
        self.osv_calls.append(queries)
        return [self.osv.get((e, n, v), []) for e, n, v in queries]


@pytest.fixture
def fake():
    return FakeRegistries
