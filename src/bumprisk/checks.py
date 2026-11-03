"""Risk checks for each dependency change."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import versions as V
from .diff import Change
from .lockfiles import NPM, PYPI
from .registry import LookupFailed, NotFound, Registries

SEVERITIES = ("critical", "high", "medium", "low", "info")
RANK = {s: i for i, s in enumerate(SEVERITIES)}
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")


@dataclass
class Finding:
    code: str
    severity: str
    message: str


@dataclass
class Result:
    change: Change
    findings: list = field(default_factory=list)
    hint: str = ""

    @property
    def severity(self) -> str:
        if not self.findings:
            return "ok"
        return min((f.severity for f in self.findings), key=RANK.get)

    def add(self, code, severity, message):
        self.findings.append(Finding(code, severity, message))


@dataclass
class Options:
    cooldown_days: float = 7.0
    new_package_days: float = 30.0
    min_downloads: int = 1000
    osv: bool = True
    now: datetime | None = None


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def ago(dt, now) -> str:
    secs = (now - dt).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min ago"
    if secs < 86400 * 2:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} days ago"


def _age_check(r: Result, published, opts, now):
    if published and (now - published).total_seconds() < opts.cooldown_days * 86400:
        r.add("too-new", "medium",
              f"{r.change.new} was published {ago(published, now)} (cooldown is {opts.cooldown_days:g} days); "
              "most hijacked releases are caught and pulled within days")


def _bump_check(r: Result):
    c = r.change
    if not c.old or c.kind != "update":
        return
    k = V.bump_kind(c.old, c.new)
    if k == "major":
        r.add("major", "low", f"breaking-change bump per semver ({c.old} -> {c.new}); read the changelog")
    elif k == "downgrade":
        r.add("downgrade", "low", f"version goes down ({c.old} -> {c.new})")
    elif k == "prerelease":
        r.add("prerelease", "low", f"{c.new} is a pre-release")


def _scripts(manifest: dict) -> dict:
    s = {k: v for k, v in (manifest.get("scripts") or {}).items() if k in INSTALL_SCRIPTS}
    if manifest.get("gypfile") and "install" not in s:
        s["install"] = "node-gyp rebuild (binding.gyp)"
    return s


def _short(s, n=70):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def check_npm(r: Result, reg: Registries, opts: Options, now):
    c = r.change
    try:
        doc = reg.npm_packument(c.name)
    except NotFound:
        r.add("not-found", "high", f"{c.name} does not exist on the npm registry (deleted, private, or a typo?)")
        return
    vers = doc.get("versions") or {}
    times = doc.get("time") or {}
    real = [v for v in vers if "security" not in v]
    if vers and not real:
        r.add("security-placeholder", "critical",
              f"npm replaced {c.name} with a security placeholder ({', '.join(vers)}): it was removed as malware")
        return
    m = vers.get(c.new)
    if m is None:
        if c.new in times:
            pub = _ts(times[c.new])
            r.add("unpublished", "high",
                  f"{c.name}@{c.new} was published {pub.date() if pub else ''} and later removed from the registry; "
                  "npm pulls compromised releases this way, and installs from this lockfile will fail")
        else:
            r.add("not-found", "high", f"{c.name}@{c.new} is not on the npm registry")
        return
    if m.get("deprecated"):
        r.add("deprecated", "medium", f"deprecated: {_short(m['deprecated'])}")
    _age_check(r, _ts(times.get(c.new)), opts, now)
    new_scripts = _scripts(m)
    old_m = vers.get(c.old) if c.old else None
    if c.old and old_m is not None:
        old_scripts = _scripts(old_m)
        added = {k: v for k, v in new_scripts.items() if k not in old_scripts}
        if added:
            k, v = next(iter(added.items()))
            r.add("install-script", "high",
                  f"new install script in {c.new}: {k}: {_short(v, 60)} (runs on npm install; {c.old} had none"
                  + ("" if not old_scripts else " of these") + ")")
        a_old, a_new = (old_m.get("dist") or {}).get("attestations"), (m.get("dist") or {}).get("attestations")
        if a_old and not a_new:
            r.add("provenance-dropped", "high",
                  f"{c.old} had npm provenance (built in CI), {c.new} has none: published from somewhere else")
        u_old = (old_m.get("_npmUser") or {}).get("name")
        u_new = (m.get("_npmUser") or {}).get("name")
        if u_old and u_new and u_old != u_new:
            r.add("publisher-changed", "medium", f"published by '{u_new}', previous version by '{u_old}'")
    elif new_scripts:
        k, v = next(iter(new_scripts.items()))
        r.add("install-script", "medium", f"runs an install script: {k}: {_short(v, 60)}")
    if c.kind == "added":
        created = _ts(times.get("created"))
        if created and (now - created).total_seconds() < opts.new_package_days * 86400:
            r.add("new-package", "medium", f"the {c.name} package itself was created {ago(created, now)}")
        dl = reg.npm_weekly_downloads(c.name)
        if dl is not None and dl < opts.min_downloads:
            r.add("low-downloads", "medium", f"only {dl} downloads last week (typosquat?)")
    _bump_check(r)
    if c.old:
        r.hint = f"npm diff --diff={c.name}@{c.old} --diff={c.name}@{c.new}"


def _pypi_files(doc, version):
    return (doc.get("releases") or {}).get(version)


def check_pypi(r: Result, reg: Registries, opts: Options, now):
    c = r.change
    try:
        doc = reg.pypi_project(c.name)
    except NotFound:
        r.add("not-found", "high", f"{c.name} is not on PyPI (deleted, private index, or a typo?)")
        return
    simple = None
    try:
        simple = reg.pypi_simple(c.name)
    except (NotFound, LookupFailed):
        pass
    status = ((simple or {}).get("project-status") or {}).get("status")
    if status == "quarantined":
        r.add("quarantined", "critical", f"PyPI has quarantined {c.name} (suspected malware)")
        return
    if status in ("archived", "deprecated"):
        r.add("project-" + status, "medium", f"PyPI marks the {c.name} project as {status}")
    files = _pypi_files(doc, c.new)
    if files is None:
        r.add("not-found", "high", f"{c.name}=={c.new} is not on PyPI (deleted or never published)")
        return
    if not files:
        r.add("no-files", "high", f"{c.name}=={c.new} has no files on PyPI (removed)")
        return
    yanked = [f for f in files if f.get("yanked")]
    if yanked and len(yanked) == len(files):
        reason = yanked[0].get("yanked_reason") or "no reason given"
        r.add("yanked", "high", f"{c.new} was yanked: {_short(reason)}")
    uploads = [t for t in (_ts(f.get("upload_time_iso_8601")) for f in files) if t]
    _age_check(r, min(uploads) if uploads else None, opts, now)
    if c.old:
        old_files = _pypi_files(doc, c.old) or []
        had_wheel = any(f.get("packagetype") == "bdist_wheel" for f in old_files)
        has_wheel = any(f.get("packagetype") == "bdist_wheel" for f in files)
        if had_wheel and not has_wheel:
            r.add("sdist-only", "medium",
                  f"{c.new} ships no wheels ({c.old} did): installing it runs the package's build code")
        if simple:
            def prov(v):
                fs = [f for f in simple.get("files", []) if _file_version(f.get("filename", ""), c.name) == v]
                return bool(fs) and all(f.get("provenance") for f in fs), bool(fs)
            p_old, seen_old = prov(c.old)
            p_new, seen_new = prov(c.new)
            if seen_old and seen_new and p_old and not p_new:
                r.add("provenance-dropped", "high",
                      f"{c.old} had PyPI attestations (trusted publishing), {c.new} does not")
    if c.kind == "added":
        all_up = [_ts(f.get("upload_time_iso_8601")) for fs in (doc.get("releases") or {}).values() for f in fs]
        all_up = [t for t in all_up if t]
        if all_up and (now - min(all_up)).total_seconds() < opts.new_package_days * 86400:
            r.add("new-package", "medium", f"the {c.name} project's first upload was {ago(min(all_up), now)}")
    _bump_check(r)


def _file_version(filename: str, name: str) -> str | None:
    base = re.sub(r"\.(tar\.gz|zip|tar\.bz2|whl|egg)$", "", filename)
    stem = re.sub(r"[-_.]+", "_", name).lower()
    parts = base.split("-")
    if len(parts) < 2:
        return None
    # wheel: name-ver-...; sdist: name-ver (name may contain dashes in old sdists)
    for i in range(1, len(parts)):
        if re.sub(r"[-_.]+", "_", "-".join(parts[:i])).lower() == stem:
            return parts[i]
    return None


def _osv(results: list, reg: Registries):
    queries, idx = [], []
    for i, r in enumerate(results):
        c = r.change
        queries.append((c.ecosystem, c.name, c.new))
        idx.append((i, "new"))
        if c.old:
            queries.append((c.ecosystem, c.name, c.old))
            idx.append((i, "old"))
    try:
        ids = reg.osv_batch(queries)
    except (LookupFailed, NotFound) as e:
        for r in results:
            r.add("osv-failed", "info", f"OSV lookup failed: {e}")
        return
    per = {}
    for (i, which), vids in zip(idx, ids):
        per.setdefault(i, {})[which] = set(vids)
    for i, d in per.items():
        r = results[i]
        new, old = d.get("new", set()), d.get("old", set())
        mal = sorted(v for v in new if v.startswith("MAL-"))
        if mal:
            r.add("malware", "critical", f"OSV lists this version as malicious: {', '.join(mal[:3])}")
        known = sorted(v for v in (new - old if r.change.old else new) if not v.startswith("MAL-"))
        if known:
            more = f" (+{len(known) - 3} more)" if len(known) > 3 else ""
            what = "that the old version didn't have" if r.change.old else "in this version"
            r.add("vulns", "high", f"{len(known)} known vulnerabilit{'y' if len(known) == 1 else 'ies'} "
                  f"{what}: {', '.join(known[:3])}{more}")
        fixed = old - new
        if fixed:
            r.add("fixes", "info", f"fixes {len(fixed)} known vulnerabilit{'y' if len(fixed) == 1 else 'ies'}")


def run(changes: list, reg: Registries | None = None, opts: Options | None = None, workers: int = 8) -> list:
    reg = reg or Registries()
    opts = opts or Options()
    now = opts.now or datetime.now(timezone.utc)
    results = [Result(c) for c in changes]

    def one(r):
        try:
            if r.change.ecosystem == NPM:
                check_npm(r, reg, opts, now)
            elif r.change.ecosystem == PYPI:
                check_pypi(r, reg, opts, now)
        except LookupFailed as e:
            r.add("lookup-failed", "medium", f"could not check the registry: {e}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, results))
    if opts.osv and results:
        _osv(results, reg)
    results.sort(key=lambda r: (RANK.get(r.severity, 9), r.change.ecosystem, r.change.name.lower()))
    return results
