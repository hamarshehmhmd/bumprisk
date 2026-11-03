from bumprisk.diff import diff, merge
from bumprisk.lockfiles import NPM


def k(name):
    return (NPM, name)


def test_update_added_removed():
    old = {k("a"): {"1.0.0"}, k("gone"): {"1.0.0"}, k("same"): {"2.0.0"}}
    new = {k("a"): {"1.1.0"}, k("b"): {"0.1.0"}, k("same"): {"2.0.0"}}
    ch = diff(old, new, "package-lock.json")
    assert [(c.name, c.old, c.new, c.kind) for c in ch] == [
        ("a", "1.0.0", "1.1.0", "update"), ("b", None, "0.1.0", "added")]
    assert ch[0].files == ["package-lock.json"]
    assert ch[0].label == "a 1.0.0 -> 1.1.0" and ch[1].label == "b 0.1.0 (new)"


def test_extra_version_and_multi_pairing():
    old = {k("ms"): {"2.0.0", "2.1.2"}}
    new = {k("ms"): {"2.0.0", "2.1.3", "3.0.0"}}
    ch = diff(old, new)
    assert [(c.old, c.new, c.kind) for c in ch] == [("2.1.2", "2.1.3", "update"), ("2.1.2", "3.0.0", "update")]
    ch = diff({k("x"): {"1.0.0"}}, {k("x"): {"1.0.0", "2.0.0"}})
    assert [(c.old, c.new, c.kind) for c in ch] == [("1.0.0", "2.0.0", "extra-version")]


def test_downgrade_pairs_with_highest_removed():
    ch = diff({k("x"): {"2.0.0"}}, {k("x"): {"1.5.0"}})
    assert (ch[0].old, ch[0].new) == ("2.0.0", "1.5.0")


def test_merge_dedupes_across_files():
    a = diff({}, {k("x"): {"1.0.0"}}, "a/package-lock.json")
    b = diff({}, {k("x"): {"1.0.0"}}, "b/package-lock.json")
    m = merge(a + b)
    assert len(m) == 1 and m[0].files == ["a/package-lock.json", "b/package-lock.json"]
