from conftest import NOW, FakeRegistries, npm_version, pypi_file

from bumprisk import checks
from bumprisk.diff import Change
from bumprisk.lockfiles import NPM, PYPI


def run(changes, reg, **kw):
    return checks.run(changes, reg=reg, opts=checks.Options(now=NOW, **kw), workers=2)


def codes(r):
    return {f.code for f in r.findings}


def doc(versions, times=None, created="2015-01-01T00:00:00Z"):
    t = {"created": created}
    t.update(times or {})
    for v in versions:
        t.setdefault(v, "2026-01-01T00:00:00Z")
    return {"versions": versions, "time": t}


def upd(name, old, new, eco=NPM):
    return Change(eco, name, new, old, "update")


def test_clean_update_has_no_findings_and_review_hint():
    reg = FakeRegistries(npm={"vite": doc({"8.3.4": npm_version(), "8.3.5": npm_version()})})
    [r] = run([upd("vite", "8.3.4", "8.3.5")], reg)
    assert r.findings == [] and r.severity == "ok"
    assert r.hint == "npm diff --diff=vite@8.3.4 --diff=vite@8.3.5"


def test_unpublished_version():
    reg = FakeRegistries(npm={"axios": doc({"1.14.0": npm_version()}, {"1.14.1": "2026-03-31T00:21:58Z"})})
    [r] = run([upd("axios", "1.14.0", "1.14.1")], reg)
    assert codes(r) == {"unpublished"} and r.severity == "high"
    assert "2026-03-31" in r.findings[0].message


def test_version_never_existed():
    reg = FakeRegistries(npm={"x": doc({"1.0.0": npm_version()})})
    [r] = run([upd("x", "1.0.0", "9.9.9")], reg)
    assert codes(r) == {"not-found"}


def test_package_missing_entirely():
    [r] = run([Change(NPM, "nope", "1.0.0")], FakeRegistries())
    assert codes(r) == {"not-found"} and r.severity == "high"


def test_security_placeholder_is_critical():
    reg = FakeRegistries(npm={"plain-crypto-js": doc({"0.0.1-security.0": npm_version()})})
    [r] = run([Change(NPM, "plain-crypto-js", "4.2.1")], reg)
    assert codes(r) == {"security-placeholder"} and r.severity == "critical"


def test_osv_malware_and_new_vulns():
    reg = FakeRegistries(
        npm={"debug": doc({"4.4.1": npm_version(), "4.4.2": npm_version()})},
        osv={(NPM, "debug", "4.4.2"): ["MAL-2025-1", "GHSA-a", "GHSA-old"], (NPM, "debug", "4.4.1"): ["GHSA-old"]})
    [r] = run([upd("debug", "4.4.1", "4.4.2")], reg)
    assert r.severity == "critical"
    vul = [f for f in r.findings if f.code == "vulns"][0]
    assert "GHSA-a" in vul.message and "GHSA-old" not in vul.message
    assert reg.osv_calls[0] == [(NPM, "debug", "4.4.2"), (NPM, "debug", "4.4.1")]


def test_osv_fixes_are_info():
    reg = FakeRegistries(npm={"u": doc({"1.0.0": npm_version(), "1.0.1": npm_version()})},
                         osv={(NPM, "u", "1.0.0"): ["GHSA-1", "GHSA-2"]})
    [r] = run([upd("u", "1.0.0", "1.0.1")], reg)
    assert codes(r) == {"fixes"} and r.severity == "info"


def test_osv_vulns_in_new_package():
    reg = FakeRegistries(npm={"n": doc({"1.0.0": npm_version()})}, osv={(NPM, "n", "1.0.0"): ["GHSA-z"]})
    [r] = run([Change(NPM, "n", "1.0.0")], reg)
    assert "vulns" in codes(r) and "in this version" in [f for f in r.findings if f.code == "vulns"][0].message


def test_osv_can_be_disabled():
    reg = FakeRegistries(npm={"n": doc({"1.0.0": npm_version()})})
    run([Change(NPM, "n", "1.0.0")], reg, osv=False)
    assert reg.osv_calls == []


def test_too_new():
    reg = FakeRegistries(npm={"nx": doc({"24.0.2": npm_version(), "24.0.3": npm_version()},
                                        {"24.0.3": "2026-11-03T09:00:00Z"})})
    [r] = run([upd("nx", "24.0.2", "24.0.3")], reg)
    assert codes(r) == {"too-new"} and "3 h ago" in r.findings[0].message
    [r] = run([upd("nx", "24.0.2", "24.0.3")], reg, cooldown_days=0)
    assert r.findings == []


def test_install_script_added_on_update():
    reg = FakeRegistries(npm={"p": doc({"1.0.0": npm_version(),
                                        "1.0.1": npm_version(scripts={"postinstall": "node setup.js"})})})
    [r] = run([upd("p", "1.0.0", "1.0.1")], reg)
    assert codes(r) == {"install-script"} and r.severity == "high"
    assert "postinstall: node setup.js" in r.findings[0].message


def test_existing_install_script_is_not_flagged_again():
    s = {"postinstall": "node install.js"}
    reg = FakeRegistries(npm={"esbuild": doc({"0.25.0": npm_version(scripts=s), "0.25.1": npm_version(scripts=s)})})
    [r] = run([upd("esbuild", "0.25.0", "0.25.1")], reg)
    assert r.findings == []


def test_gypfile_counts_as_install_script_for_new_package():
    reg = FakeRegistries(npm={"native": doc({"1.0.0": npm_version(gypfile=True)})})
    [r] = run([Change(NPM, "native", "1.0.0")], reg)
    f = [f for f in r.findings if f.code == "install-script"][0]
    assert f.severity == "medium" and "node-gyp" in f.message


def test_provenance_dropped_and_publisher_changed():
    reg = FakeRegistries(npm={"axios": doc({
        "1.14.0": npm_version(user="GitHub Actions", attest=True),
        "1.14.1": npm_version(user="jasonsaayman")})})
    [r] = run([upd("axios", "1.14.0", "1.14.1")], reg)
    assert codes(r) == {"provenance-dropped", "publisher-changed"} and r.severity == "high"


def test_deprecated():
    reg = FakeRegistries(npm={"q": doc({"1.0.0": npm_version(), "1.1.0": npm_version(deprecated="use x instead")})})
    [r] = run([upd("q", "1.0.0", "1.1.0")], reg)
    assert codes(r) == {"deprecated"}


def test_new_young_low_download_package():
    reg = FakeRegistries(npm={"reqeusts": doc({"1.0.0": npm_version()}, created="2026-10-30T00:00:00Z")},
                         downloads={"reqeusts": 12})
    [r] = run([Change(NPM, "reqeusts", "1.0.0")], reg)
    assert codes(r) == {"new-package", "low-downloads"}


def test_major_and_downgrade_are_low():
    reg = FakeRegistries(npm={"t": doc({"5.9.0": npm_version(), "6.0.0": npm_version(), "5.8.0": npm_version()})})
    [a, b] = sorted(run([upd("t", "5.9.0", "6.0.0"), Change(NPM, "t", "5.8.0", "5.9.0", "update")], reg),
                    key=lambda r: r.change.new)
    assert codes(a) == {"downgrade"} and codes(b) == {"major"} and b.severity == "low"


def test_lookup_failure_is_reported_not_raised():
    from bumprisk.registry import LookupFailed

    class Broken(FakeRegistries):
        def npm_packument(self, name):
            raise LookupFailed("timeout")

        def osv_batch(self, q):
            raise LookupFailed("osv down")

    [r] = run([Change(NPM, "x", "1.0.0")], Broken())
    assert codes(r) == {"lookup-failed", "osv-failed"}


# PyPI --------------------------------------------------------------------

def proj(releases):
    return {"releases": releases}


def test_pypi_yanked():
    reg = FakeRegistries(pypi={"requests": proj({
        "2.31.0": [pypi_file()],
        "2.32.0": [pypi_file(yanked=True, reason="conflicts with CVE mitigation"),
                   pypi_file("sdist", yanked=True)]})})
    [r] = run([upd("requests", "2.31.0", "2.32.0", PYPI)], reg)
    assert codes(r) == {"yanked"} and "conflicts" in r.findings[0].message


def test_pypi_missing_version_and_project():
    reg = FakeRegistries(pypi={"ultralytics": proj({"8.3.40": [pypi_file()]})})
    [r] = run([upd("ultralytics", "8.3.40", "8.3.41", PYPI)], reg)
    assert codes(r) == {"not-found"}
    [r] = run([Change(PYPI, "nothere", "1.0")], FakeRegistries())
    assert codes(r) == {"not-found"}


def test_pypi_no_files():
    reg = FakeRegistries(pypi={"x": proj({"1.0": [pypi_file()], "1.1": []})})
    [r] = run([upd("x", "1.0", "1.1", PYPI)], reg)
    assert codes(r) == {"no-files"}


def test_pypi_quarantined():
    reg = FakeRegistries(pypi={"evil": proj({"1.0": [pypi_file()]})},
                         simple={"evil": {"project-status": {"status": "quarantined"}, "files": []}})
    [r] = run([Change(PYPI, "evil", "1.0")], reg)
    assert codes(r) == {"quarantined"} and r.severity == "critical"


def test_pypi_sdist_only_and_too_new():
    reg = FakeRegistries(pypi={"lib": proj({
        "1.0": [pypi_file(), pypi_file("sdist")],
        "1.1": [pypi_file("sdist", when="2026-11-02T12:00:00Z")]})})
    [r] = run([upd("lib", "1.0", "1.1", PYPI)], reg)
    assert codes(r) == {"sdist-only", "too-new"}


def test_pypi_provenance_dropped():
    def f(name, prov):
        return {"filename": name, "provenance": "https://pypi.org/integrity/x" if prov else None}
    simple = {"files": [f("my_lib-1.0-py3-none-any.whl", True), f("my_lib-1.0.tar.gz", True),
                        f("my_lib-1.1-py3-none-any.whl", False)]}
    reg = FakeRegistries(pypi={"my-lib": proj({"1.0": [pypi_file()], "1.1": [pypi_file()]})},
                         simple={"my-lib": simple})
    [r] = run([upd("my-lib", "1.0", "1.1", PYPI)], reg)
    assert codes(r) == {"provenance-dropped"}


def test_pypi_new_project():
    reg = FakeRegistries(pypi={"fresh": proj({"0.1": [pypi_file(when="2026-10-25T00:00:00Z")]})})
    [r] = run([Change(PYPI, "fresh", "0.1")], reg)
    assert codes(r) == {"new-package"}


def test_file_version_parsing():
    fv = checks._file_version
    assert fv("my_lib-1.0-py3-none-any.whl", "my-lib") == "1.0"
    assert fv("my-lib-2.0.tar.gz", "my-lib") == "2.0"
    assert fv("Django-5.0.zip", "django") == "5.0"
    assert fv("other-1.0.tar.gz", "my-lib") is None


def test_results_sorted_worst_first():
    reg = FakeRegistries(npm={"ok": doc({"1.0.0": npm_version(), "1.0.1": npm_version()})})
    res = run([upd("ok", "1.0.0", "1.0.1"), Change(NPM, "missing", "1.0.0")], reg)
    assert [r.change.name for r in res] == ["missing", "ok"]


def test_ago():
    from datetime import timedelta
    assert checks.ago(NOW - timedelta(minutes=5), NOW) == "5 min ago"
    assert checks.ago(NOW - timedelta(hours=30), NOW) == "30 h ago"
    assert checks.ago(NOW - timedelta(days=4), NOW) == "4 days ago"
