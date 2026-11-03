"""Parse lockfiles into {(ecosystem, name): {versions}}.

Supported: package-lock.json / npm-shrinkwrap.json (v1-v3), yarn.lock (classic and berry),
pnpm-lock.yaml (v5-v9), requirements*.txt (== pins), poetry.lock, uv.lock, pdm.lock, Pipfile.lock.
Only packages that come from a registry are returned; workspace, git, file and link entries are skipped.
"""
from __future__ import annotations

import json
import os
import re
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

NPM, PYPI = "npm", "PyPI"

NPM_FILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
PY_FILES = ("poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock")


class LockfileError(ValueError):
    pass


def kind_of(path: str) -> str | None:
    base = os.path.basename(path)
    if base in ("package-lock.json", "npm-shrinkwrap.json"):
        return "npm-lock"
    if base == "yarn.lock":
        return "yarn"
    if base == "pnpm-lock.yaml":
        return "pnpm"
    if base in ("poetry.lock", "uv.lock", "pdm.lock"):
        return "toml-lock"
    if base == "Pipfile.lock":
        return "pipfile"
    if re.match(r"^(.*requirements.*|constraints.*)\.txt$", base, re.I):
        return "requirements"
    parent = os.path.basename(os.path.dirname(path.replace("\\", "/")))
    if base.endswith(".txt") and parent.lower() == "requirements":
        return "requirements"
    return None


def is_lockfile(path: str) -> bool:
    return kind_of(path) is not None


def norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _add(out, eco, name, version):
    if name and version:
        out.setdefault((eco, name), set()).add(version)


def parse(text: str, path: str, kind: str | None = None) -> dict:
    kind = kind or kind_of(path)
    if kind is None:
        raise LockfileError(f"don't know how to read {path}")
    if not text.strip():
        return {}
    try:
        return _PARSERS[kind](text)
    except LockfileError:
        raise
    except Exception as e:  # malformed input
        raise LockfileError(f"could not parse {path}: {e}") from e


def _registry_resolved(resolved) -> bool:
    if not resolved:
        return True  # old lockfiles omit it for registry deps
    return resolved.startswith(("http://", "https://")) and ".tgz" in resolved


def parse_npm_lock(text: str) -> dict:
    data = json.loads(text)
    out: dict = {}
    pkgs = data.get("packages")
    if isinstance(pkgs, dict):
        for key, e in pkgs.items():
            if not key or "node_modules/" not in key or e.get("link") or e.get("inBundle"):
                continue
            if not _registry_resolved(e.get("resolved")):
                continue
            name = e.get("name") or key.rsplit("node_modules/", 1)[1]
            _add(out, NPM, name, e.get("version"))
        return out

    def walk(deps):
        for name, e in (deps or {}).items():
            v = e.get("version", "")
            if v.startswith("npm:"):  # alias: "npm:real@1.2.3"
                name, _, v = v[4:].rpartition("@")
            if e.get("bundled") or not re.match(r"^\d", v) or not _registry_resolved(e.get("resolved")):
                pass
            else:
                _add(out, NPM, name, v)
            walk(e.get("dependencies"))

    walk(data.get("dependencies"))
    return out


def _spec_name(spec: str) -> str:
    spec = spec.strip().strip('"')
    if spec.startswith("@"):
        return "@" + spec[1:].split("@", 1)[0]
    return spec.split("@", 1)[0]


def parse_yarn(text: str) -> dict:
    out: dict = {}
    name = None
    resolution_ok = True
    version = None

    def flush():
        if name and version and resolution_ok:
            _add(out, NPM, name, version)

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            flush()
            header = line.rstrip(":").strip()
            first = header.split(",")[0].strip().strip('"')
            name = None if first.startswith("__metadata") else _spec_name(first)
            # berry: "pkg@npm:^1.0.0"; skip workspace/patch/git/file protocols
            rest = first[len(name or "") + 1:] if name else ""
            resolution_ok = not re.match(r"^(workspace|portal|link|file|git|github|patch|exec):", rest)
            version = None
            continue
        s = line.strip()
        m = re.match(r'^version:?\s+"?([^"\s]+)"?$', s)
        if m and line.startswith("  ") and not line.startswith("    "):
            version = m.group(1)
            continue
        m = re.match(r'^resolution:\s+"?(.+?)"?$', s)
        if m:
            res = m.group(1)
            rname = _spec_name(res)
            proto = res[len(rname) + 1:]
            if not proto.startswith("npm:"):
                resolution_ok = False
            else:
                name = rname
        m = re.match(r'^resolved\s+"?([^"\s]+)"?$', s)
        if m and not _registry_resolved(m.group(1)):
            resolution_ok = False
    flush()
    return out


_PNPM_KEY = re.compile(r"^  ['\"]?/?((?:@[^/@\s]+/)?[^@\s'\"(]+)[@/]([0-9][^'\"(:\s]*)")


def parse_pnpm(text: str) -> dict:
    out: dict = {}
    section = None
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section = line.rstrip(":").strip()
            continue
        if section not in ("packages", "snapshots"):
            continue
        m = _PNPM_KEY.match(line)
        if m:
            _add(out, NPM, m.group(1), m.group(2))
    return out


def parse_requirements(text: str) -> dict:
    out: dict = {}
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            continue
        line = line.split(";", 1)[0].rstrip("\\").strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*===?\s*([^\s,]+)$", line)
        if m:
            _add(out, PYPI, norm_py(m.group(1)), m.group(3))
    return out


def parse_toml_lock(text: str) -> dict:
    data = tomllib.loads(text)
    out: dict = {}
    for p in data.get("package", []):
        src = p.get("source")
        if isinstance(src, dict):
            # uv: {registry = "..."} is fine; editable/virtual/git/path/directory are local
            if any(k in src for k in ("editable", "virtual", "git", "path", "directory", "url")):
                continue
            if src.get("type") in ("git", "directory", "file", "url"):  # poetry
                continue
        _add(out, PYPI, norm_py(p.get("name", "")), p.get("version"))
    return out


def parse_pipfile(text: str) -> dict:
    data = json.loads(text)
    out: dict = {}
    for section in ("default", "develop"):
        for name, e in (data.get(section) or {}).items():
            v = (e.get("version") or "") if isinstance(e, dict) else ""
            if v.startswith("=="):
                _add(out, PYPI, norm_py(name), v[2:])
    return out


_PARSERS = {
    "npm-lock": parse_npm_lock,
    "yarn": parse_yarn,
    "pnpm": parse_pnpm,
    "requirements": parse_requirements,
    "toml-lock": parse_toml_lock,
    "pipfile": parse_pipfile,
}
