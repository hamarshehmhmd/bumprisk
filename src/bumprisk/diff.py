"""Turn two parsed lockfiles into a list of dependency changes."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import versions as V


@dataclass
class Change:
    ecosystem: str
    name: str
    new: str
    old: str | None = None       # None: package is new to the lockfile
    kind: str = "added"          # added | update | extra-version
    files: list = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.old:
            return f"{self.name} {self.old} -> {self.new}"
        return f"{self.name} {self.new} (new)"


def diff(old: dict, new: dict, path: str = "") -> list:
    changes = []
    for key in sorted(new, key=lambda k: (k[0], k[1].lower())):
        eco, name = key
        nv, ov = new[key], old.get(key, set())
        added = nv - ov
        if not added:
            continue
        removed = ov - nv
        for v in sorted(added, key=V.parse):
            if removed:
                # pair with the closest removed version below (or the highest removed one)
                below = [r for r in removed if V.compare(r, v) <= 0]
                prev = V.highest(below) if below else V.highest(removed)
                changes.append(Change(eco, name, v, prev, "update", [path] if path else []))
            elif ov:
                changes.append(Change(eco, name, v, V.highest(ov), "extra-version", [path] if path else []))
            else:
                changes.append(Change(eco, name, v, None, "added", [path] if path else []))
    return changes


def merge(changes: list) -> list:
    """Collapse identical changes found in several lockfiles."""
    seen: dict = {}
    for c in changes:
        k = (c.ecosystem, c.name, c.old, c.new)
        if k in seen:
            for f in c.files:
                if f not in seen[k].files:
                    seen[k].files.append(f)
        else:
            seen[k] = c
    return list(seen.values())
