"""Text, Markdown and JSON output."""
from __future__ import annotations

import json
import os
import sys

from . import __version__
from .checks import RANK

ICON = {"critical": "✖", "high": "✖", "medium": "▲", "low": "•", "info": "·", "ok": "✔"}
COLOR = {"critical": "31;1", "high": "31", "medium": "33", "low": "36", "info": "2", "ok": "32"}
MD_ICON = {"critical": "🛑", "high": "🔴", "medium": "🟡", "low": "🔵", "info": "⚪", "ok": "🟢"}


def use_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def counts(results) -> dict:
    out = {s: 0 for s in ("critical", "high", "medium", "low", "ok")}
    for r in results:
        sev = r.severity if r.severity != "info" else "ok"
        out[sev] += 1
    return out


def summary_line(results) -> str:
    c = counts(results)
    parts = [f"{n} {s}" for s, n in c.items() if n]
    return f"{len(results)} changed package{'s' if len(results) != 1 else ''}: " + (", ".join(parts) or "none")


def text(results, verbose=False, stream=None) -> str:
    stream = stream or sys.stdout
    col = use_color(stream)

    def paint(s, code):
        return f"\x1b[{code}m{s}\x1b[0m" if col else s

    lines = []
    if not results:
        return "no dependency changes found\n"
    for r in results:
        sev = r.severity
        if sev in ("ok", "info") and not verbose:
            continue
        c = r.change
        tag = paint(f"{ICON[sev]} {sev.upper():8}", COLOR[sev])
        lines.append(f"{tag} {paint(c.label, '1')}  [{c.ecosystem}]")
        for f in sorted(r.findings, key=lambda f: RANK[f.severity]):
            if f.severity == "info" and not verbose:
                continue
            lines.append(f"    {paint(ICON[f.severity], COLOR[f.severity])} {f.message}")
        if r.hint and sev in ("critical", "high", "medium"):
            lines.append(paint(f"    review: {r.hint}", "2"))
    quiet = [r for r in results if r.severity in ("ok", "info")]
    if quiet and not verbose:
        names = ", ".join(r.change.label for r in quiet[:6])
        more = f" and {len(quiet) - 6} more" if len(quiet) > 6 else ""
        lines.append(paint(f"{ICON['ok']} {len(quiet)} look fine: {names}{more}", COLOR["ok"]))
    lines.append("")
    lines.append(summary_line(results))
    return "\n".join(lines) + "\n"


def markdown(results, title="bumprisk") -> str:
    out = [f"### {title}: {summary_line(results)}", ""]
    flagged = [r for r in results if r.severity not in ("ok", "info")]
    if flagged:
        out += ["| | Package | Change | Findings |", "|---|---|---|---|"]
        for r in flagged:
            c = r.change
            change = f"{c.old} → {c.new}" if c.old else f"new: {c.new}"
            fs = "<br>".join(f"{MD_ICON[f.severity]} {f.message}".replace("|", "\\|")
                             for f in sorted(r.findings, key=lambda f: RANK[f.severity]) if f.severity != "info")
            out.append(f"| {MD_ICON[r.severity]} | `{c.name}` ({c.ecosystem}) | {change} | {fs} |")
        out.append("")
    ok = [r for r in results if r.severity in ("ok", "info")]
    if ok:
        out.append(f"<details><summary>{len(ok)} change(s) with no findings</summary>\n")
        out += [f"- `{r.change.label}`" for r in ok]
        out.append("\n</details>")
    out.append(f"\n<sub>bumprisk {__version__}: registry metadata + OSV.dev. "
               "Findings are signals to review, not proof of compromise.</sub>")
    return "\n".join(out) + "\n"


def as_json(results) -> str:
    return json.dumps({
        "version": __version__,
        "summary": counts(results),
        "changes": [{
            "ecosystem": r.change.ecosystem, "name": r.change.name, "old": r.change.old, "new": r.change.new,
            "kind": r.change.kind, "files": r.change.files, "severity": r.severity, "review": r.hint or None,
            "findings": [{"code": f.code, "severity": f.severity, "message": f.message} for f in r.findings],
        } for r in results],
    }, indent=2) + "\n"
