"""Find changed lockfiles between two git revisions (or a revision and the working tree)."""
from __future__ import annotations

import os
import subprocess

from .lockfiles import is_lockfile


class GitError(RuntimeError):
    pass


def git(*args, cwd=None) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise GitError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout


def toplevel(cwd=None) -> str:
    return git("rev-parse", "--show-toplevel", cwd=cwd).strip()


def default_base(cwd=None) -> str:
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        return f"origin/{base_ref}"
    return "HEAD"


def merge_base(base: str, head: str | None, cwd=None) -> str:
    try:
        return git("merge-base", base, head or "HEAD", cwd=cwd).strip()
    except GitError:
        return base


def changed_lockfiles(base: str, head: str | None, cwd=None) -> list:
    args = ["diff", "--name-only", "--no-renames", base] + ([head] if head else [])
    names = git(*args, cwd=cwd).splitlines()
    if not head:  # include untracked lockfiles in the working tree
        names += git("ls-files", "--others", "--exclude-standard", cwd=cwd).splitlines()
    return sorted({n for n in names if is_lockfile(n) and "node_modules/" not in n})


def read_at(rev: str | None, path: str, cwd=None) -> str:
    if rev is None:
        full = os.path.join(cwd or ".", path)
        if not os.path.exists(full):
            return ""
        with open(full, encoding="utf-8") as fh:
            return fh.read()
    try:
        return git("show", f"{rev}:{path}", cwd=cwd)
    except GitError:
        return ""  # file didn't exist at that revision
