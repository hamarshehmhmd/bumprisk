import json
import os
import subprocess

import pytest
from conftest import NOW, FakeRegistries, npm_version

from bumprisk import checks, cli, report

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def lockv3(deps):
    pk = {"": {"name": "app"}}
    pk.update({f"node_modules/{n}": {"version": v} for n, v in deps.items()})
    return json.dumps({"lockfileVersion": 3, "packages": pk}, indent=2)


REG = FakeRegistries(
    npm={
        "axios": {"versions": {"1.14.0": npm_version()}, "time": {"1.14.0": "2026-03-27T00:00:00Z",
                                                                  "1.14.1": "2026-03-31T00:21:58Z"}},
        "plain-crypto-js": {"versions": {"0.0.1-security.0": npm_version()}, "time": {}},
        "chalk": {"versions": {"5.3.0": npm_version(), "5.6.1": npm_version()}, "time": {}},
        "debug": {"versions": {"4.4.1": npm_version()}, "time": {"4.4.2": "2025-09-08T00:00:00Z"}},
        "ms": {"versions": {"2.1.3": npm_version()}, "time": {}},
        "vite": {"versions": {"8.3.4": npm_version(), "8.3.5": npm_version()}, "time": {}},
        "follow-redirects": {"versions": {"1.15.11": npm_version()}, "time": {}},
        "form-data": {"versions": {"4.0.4": npm_version()}, "time": {}},
        "proxy-from-env": {"versions": {"1.1.0": npm_version()}, "time": {}},
    },
    osv={("npm", "chalk", "5.6.1"): ["MAL-2025-46969"]})


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(checks, "Registries", lambda: REG)
    real_options = checks.Options
    monkeypatch.setattr(checks, "Options", lambda **kw: real_options(now=NOW, **kw))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


def test_compare_example_fails_with_findings(capsys):
    rc = cli.main(["compare", f"{EX}/npm/old/package-lock.json", f"{EX}/npm/new/package-lock.json"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "CRITICAL plain-crypto-js 4.2.1 (new)" in out
    assert "axios@1.14.1 was published 2026-03-31 and later removed" in out
    assert "MAL-2025-46969" in out
    assert "1 look fine: vite 8.3.4 -> 8.3.5" in out
    assert out.strip().endswith("5 changed packages: 2 critical, 2 high, 1 ok")


def test_fail_on_never_and_json(capsys):
    rc = cli.main(["compare", f"{EX}/npm/old/package-lock.json", f"{EX}/npm/new/package-lock.json",
                   "--fail-on", "never", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["summary"]["critical"] == 2
    by = {c["name"]: c for c in data["changes"]}
    assert by["axios"]["findings"][0]["code"] == "unpublished"
    assert by["vite"]["review"] == "npm diff --diff=vite@8.3.4 --diff=vite@8.3.5"


def test_fail_on_threshold(tmp_path):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(lockv3({"vite": "8.3.4"}))
    new.write_text(lockv3({"vite": "8.3.5"}))
    assert cli.main(["compare", str(old), str(new), "--as", "package-lock.json"]) == 0
    new.write_text(lockv3({"vite": "8.3.5", "ms": "2.1.3"}))  # new package: no findings either
    assert cli.main(["compare", str(old), str(new), "--as", "package-lock.json", "--fail-on", "low"]) == 0


def test_markdown_output_file_and_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    out = tmp_path / "report.txt"
    cli.main(["compare", f"{EX}/npm/old/package-lock.json", f"{EX}/npm/new/package-lock.json", "-o", str(out)])
    assert "CRITICAL" in out.read_text()
    md = summary.read_text()
    assert md.startswith("### bumprisk: 5 changed packages")
    assert "| 🛑 | `chalk` (npm) | 5.3.0 → 5.6.1 |" in md
    assert "<details><summary>1 change(s) with no findings</summary>" in md


def test_unknown_lockfile_type(tmp_path, capsys):
    a = tmp_path / "a.lock"
    a.write_text("x")
    assert cli.main(["compare", str(a), str(a)]) == 2
    assert "--as" in capsys.readouterr().err


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package-lock.json").write_text(lockv3({"vite": "8.3.4", "axios": "1.14.0"}))
    (tmp_path / "requirements.txt").write_text("")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_diff_working_tree(repo, capsys):
    (repo / "web" / "package-lock.json").write_text(lockv3({"vite": "8.3.5", "axios": "1.14.1"}))
    rc = cli.main(["diff"])
    out = capsys.readouterr().out
    assert rc == 1 and "axios 1.14.0 -> 1.14.1" in out and "2 changed packages" in out


def test_diff_between_commits_and_new_lockfile(repo, capsys):
    (repo / "web" / "package-lock.json").write_text(lockv3({"vite": "8.3.5", "axios": "1.14.0"}))
    (repo / "api").mkdir()
    (repo / "api" / "package-lock.json").write_text(lockv3({"ms": "2.1.3"}))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "bump")
    rc = cli.main(["diff", "--base", "HEAD~1", "--head", "HEAD", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert sorted((c["name"], c["old"], c["new"]) for c in data["changes"]) == [
        ("ms", None, "2.1.3"), ("vite", "8.3.4", "8.3.5")]
    # restricting to one path
    cli.main(["diff", "--base", "HEAD~1", "--head", "HEAD", "--format", "json", "api/package-lock.json"])
    data = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in data["changes"]] == ["ms"]


def test_diff_uses_github_base_ref(repo, capsys, monkeypatch):
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-qb", "feature")
    (repo / "web" / "package-lock.json").write_text(lockv3({"vite": "8.3.5", "axios": "1.14.0"}))
    git(repo, "commit", "-qam", "bump vite")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    assert cli.main(["diff", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(c["name"], c["new"]) for c in data["changes"]] == [("vite", "8.3.5")]


def test_diff_nothing_changed(repo, capsys):
    assert cli.main(["diff"]) == 0
    io = capsys.readouterr()
    assert "no changed lockfiles since HEAD" in io.err
    assert "no dependency changes found" in io.out


def test_diff_outside_git(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["diff"]) == 2


def test_text_report_verbose_and_color(monkeypatch):
    from bumprisk.diff import Change
    r = checks.Result(Change("npm", "x", "1.0.1", "1.0.0", "update"))
    r.add("fixes", "info", "fixes 1 known vulnerability")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR")
    out = report.text([r], verbose=True)
    assert "\x1b[" in out and "fixes 1 known" in out
    monkeypatch.setenv("NO_COLOR", "1")
    assert "1 look fine: x 1.0.0 -> 1.0.1" in report.text([r])
