import pytest

from bumprisk import versions as V


@pytest.mark.parametrize("old,new,kind", [
    ("1.2.3", "2.0.0", "major"),
    ("0.3.1", "0.4.0", "major"),
    ("0.3.1", "0.3.2", "patch"),
    ("1.2.3", "1.3.0", "minor"),
    ("1.2.3", "1.2.4", "patch"),
    ("1.2.3", "1.2.3", "same"),
    ("2.0.0", "1.9.9", "downgrade"),
    ("1.2.3", "1.3.0-beta.1", "prerelease"),
    ("1.0", "1.0.1", "patch"),
    ("4.0.0", "4.0.0.post1", "patch"),
])
def test_bump_kind(old, new, kind):
    assert V.bump_kind(old, new) == kind


def test_prerelease_sorts_before_final():
    assert V.compare("2.0.0-rc.1", "2.0.0") < 0
    assert V.compare("2.0.0rc1", "2.0.0") < 0
    assert V.highest(["1.9.0", "1.10.0", "1.2.0"]) == "1.10.0"


def test_post_release_after_final():
    assert V.compare("1.0.0.post1", "1.0.0") > 0


def test_garbage_versions_do_not_crash():
    assert V.parse("latest")[0] == (0,)
    assert V.bump_kind("latest", "1.0.0") in ("major", "downgrade", "minor", "patch", "same", "prerelease")
