"""Small, dependency-free version helpers that are good enough for risk triage.

They are not full semver / PEP 440 implementations: they only need to order
versions of one package and tell whether an update crosses a breaking boundary.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"\d+")


def parse(version: str) -> tuple:
    """Return a sortable key: (release numbers..., is_final, pre-release text)."""
    v = version.strip().lstrip("vV=")
    v = v.split("+", 1)[0]
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((0,), 0, v)
    nums = tuple(int(x) for x in m.group(1).split("."))
    while len(nums) < 3:
        nums = nums + (0,)
    rest = m.group(2).lstrip(".-_")
    # final releases sort after pre-releases; post releases (".post1") after finals
    if not rest:
        return (nums, 1, "")
    low = rest.lower()
    if low.startswith(("post", "r", "rev")) and not low.startswith("rc"):
        return (nums, 2, low)
    return (nums, 0, low)


def is_prerelease(version: str) -> bool:
    return parse(version)[1] == 0 and bool(parse(version)[2])


def compare(a: str, b: str) -> int:
    ka, kb = parse(a), parse(b)
    return (ka > kb) - (ka < kb)


def highest(versions) -> str:
    return max(versions, key=parse)


def bump_kind(old: str, new: str) -> str:
    """'major', 'minor', 'patch', 'prerelease', 'downgrade' or 'same'.

    For 0.x versions a minor bump is treated as major (semver: anything may break).
    """
    c = compare(new, old)
    if c == 0:
        return "same"
    if c < 0:
        return "downgrade"
    o, n = parse(old)[0], parse(new)[0]
    if o[0] != n[0]:
        return "major"
    if o[0] == 0 and o[1] != n[1]:
        return "major"
    if is_prerelease(new):
        return "prerelease"
    if o[1] != n[1]:
        return "minor"
    return "patch"
