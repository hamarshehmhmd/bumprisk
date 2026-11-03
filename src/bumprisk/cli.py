"""bumprisk command line."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, checks, report
from .diff import diff, merge
from .gitdiff import GitError, changed_lockfiles, default_base, merge_base, read_at, toplevel
from .lockfiles import LockfileError, kind_of, parse

FAIL_LEVELS = ("critical", "high", "medium", "low", "never")


def build_parser():
    p = argparse.ArgumentParser(
        prog="bumprisk",
        description="See what a lockfile change really pulls in before you merge it: removed or malicious "
                    "versions, brand-new releases, new install scripts, lost provenance, publisher changes, "
                    "yanked versions and known vulnerabilities. npm, Yarn, pnpm and Python lockfiles.")
    p.add_argument("--version", action="version", version=f"bumprisk {__version__}")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--cooldown", type=float, default=7, metavar="DAYS",
                        help="flag versions published less than DAYS ago (default 7)")
        sp.add_argument("--fail-on", choices=FAIL_LEVELS, default="high",
                        help="exit 1 if any finding is at least this severe (default high)")
        sp.add_argument("--format", choices=("text", "markdown", "json"), default="text")
        sp.add_argument("-o", "--output", help="write the report to a file instead of stdout")
        sp.add_argument("-v", "--verbose", action="store_true", help="also list changes with no findings")
        sp.add_argument("--no-osv", action="store_true", help="skip the OSV.dev vulnerability/malware lookup")

    d = sub.add_parser("diff", help="check lockfiles changed in git (default: working tree vs HEAD, "
                                    "or vs origin/$GITHUB_BASE_REF in a pull request)")
    d.add_argument("--base", help="base revision (default: origin/$GITHUB_BASE_REF or HEAD)")
    d.add_argument("--head", help="head revision (default: the working tree)")
    d.add_argument("paths", nargs="*", help="only these lockfiles")
    common(d)

    c = sub.add_parser("compare", help="compare two lockfiles directly")
    c.add_argument("old")
    c.add_argument("new")
    c.add_argument("--as", dest="as_name", metavar="FILENAME",
                   help="treat both files as this lockfile type, e.g. package-lock.json")
    common(c)
    return p


def _read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def collect_compare(a) -> list:
    name = a.as_name or a.new
    if kind_of(name) is None:
        raise LockfileError(f"don't know the lockfile type of {a.new}; pass --as package-lock.json (or similar)")
    old = parse(_read(a.old), name)
    new = parse(_read(a.new), name)
    return diff(old, new, a.new)


def collect_git(a) -> tuple:
    top = toplevel()
    base = a.base or default_base()
    base = merge_base(base, a.head, cwd=top) if a.base is None and os.environ.get("GITHUB_BASE_REF") else base
    files = changed_lockfiles(base, a.head, cwd=top)
    if a.paths:
        want = {os.path.relpath(os.path.abspath(p), top) for p in a.paths}
        files = [f for f in files if f in want]
    changes = []
    for f in files:
        old = parse(read_at(base, f, cwd=top), f)
        new = parse(read_at(a.head, f, cwd=top), f)
        changes += diff(old, new, f)
    return merge(changes), files, base


def main(argv=None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not a.cmd:
        parser.print_help()
        return 2
    try:
        if a.cmd == "compare":
            changes, files = merge(collect_compare(a)), [a.new]
        else:
            changes, files, base = collect_git(a)
            if not files and a.format == "text":
                print(f"no changed lockfiles since {base}", file=sys.stderr)
    except (LockfileError, GitError) as e:
        print(f"bumprisk: {e}", file=sys.stderr)
        return 2
    opts = checks.Options(cooldown_days=a.cooldown, osv=not a.no_osv)
    results = checks.run(changes, opts=opts)

    out_stream = open(a.output, "w", encoding="utf-8") if a.output else sys.stdout
    try:
        if a.format == "json":
            out_stream.write(report.as_json(results))
        elif a.format == "markdown":
            out_stream.write(report.markdown(results))
        else:
            out_stream.write(report.text(results, verbose=a.verbose, stream=out_stream))
    finally:
        if a.output:
            out_stream.close()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and a.format != "markdown" and results:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report.markdown(results))

    if a.fail_on == "never":
        return 0
    limit = checks.RANK[a.fail_on]
    worst = min((checks.RANK[f.severity] for r in results for f in r.findings), default=99)
    return 1 if worst <= limit else 0
