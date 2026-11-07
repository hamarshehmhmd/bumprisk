"""Regression tests for the composite action's input handling.

The v0.1.0 action pasted inputs into `run:`. Under the runner shell
(`bash -eo pipefail`) that executes `$(...)` inside double quotes, and `;` / `||`
when the surrounding command succeeds or fails. These tests keep the supported
command lines (including quotes and backslashes) and require metacharacters to
stay literal argv text.
"""
import json
import os
import re
import shlex
import subprocess

import pytest
from conftest import NOW, FakeRegistries, npm_version

from bumprisk import __version__, action, checks
from bumprisk.cli import build_parser

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Feather icons GitHub accepts for Marketplace branding (metadata syntax,
# icon set v4.28.0) minus the omitted brand / utility icons.
_MARKETPLACE_ICONS = set("""
activity airplay alert-circle alert-octagon alert-triangle align-center align-justify
align-left align-right anchor aperture archive arrow-down-circle arrow-down-left
arrow-down-right arrow-down arrow-left-circle arrow-left arrow-right-circle arrow-right
arrow-up-circle arrow-up-left arrow-up-right arrow-up at-sign award bar-chart-2 bar-chart
battery-charging battery bell-off bell bluetooth bold book-open book bookmark box
briefcase calendar camera-off camera cast check-circle check-square check chevron-down
chevron-left chevron-right chevron-up chevrons-down chevrons-left chevrons-right
chevrons-up circle clipboard clock cloud-drizzle cloud-lightning cloud-off cloud-rain
cloud-snow cloud code command compass copy corner-down-left corner-down-right
corner-left-down corner-left-up corner-right-down corner-right-up corner-up-left
corner-up-right cpu credit-card crop crosshair database delete disc dollar-sign
download-cloud download droplet edit-2 edit-3 edit external-link eye-off eye
fast-forward feather file-minus file-plus file-text file film filter flag folder-minus
folder-plus folder gift git-branch git-commit git-merge git-pull-request globe grid
hard-drive hash headphones heart help-circle home image inbox info italic layers layout
life-buoy link-2 link list loader lock log-in log-out mail map-pin map maximize-2
maximize menu message-circle message-square mic-off mic minimize-2 minimize minus-circle
minus-square minus monitor moon more-horizontal more-vertical move music navigation-2
navigation octagon package paperclip pause-circle pause percent phone-call
phone-forwarded phone-incoming phone-missed phone-off phone-outgoing phone pie-chart
play-circle play plus-circle plus-square plus pocket power printer radio refresh-ccw
refresh-cw repeat rewind rotate-ccw rotate-cw rss save scissors search send server
settings share-2 share shield-off shield shopping-bag shopping-cart shuffle sidebar
skip-back skip-forward slash sliders smartphone speaker square star stop-circle sun
sunrise sunset table tablet tag target terminal thermometer thumbs-down thumbs-up
toggle-left toggle-right trash-2 trash trending-down trending-up triangle truck tv type
umbrella underline unlock upload-cloud upload user-check user-minus user-plus user-x
user users video-off video voicemail volume-1 volume-2 volume-x volume watch wifi-off
wifi wind x-circle x-square x zap-off zap zoom-in zoom-out
""".split())
_OMITTED_ICONS = {
    "coffee", "columns", "divide-circle", "divide-square", "divide", "frown", "hexagon",
    "key", "meh", "mouse-pointer", "smile", "tool", "x-octagon",
}
_BRAND_COLORS = {"white", "black", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"}
_INSTALL_RUN = (
    'python3 -m pip install --quiet --disable-pip-version-check "$BUMPRISK_ACTION_PATH" '
    '|| python3 -m pip install --quiet --break-system-packages "$BUMPRISK_ACTION_PATH"'
)


def lockv3(deps):
    pk = {"": {"name": "app"}}
    pk.update({f"node_modules/{n}": {"version": v} for n, v in deps.items()})
    return json.dumps({"lockfileVersion": 3, "packages": pk}, indent=2)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    reg = FakeRegistries(npm={
        "axios": {"versions": {"1.14.0": npm_version()},
                  "time": {"1.14.0": "2026-03-27T00:00:00Z", "1.14.1": "2026-03-31T00:21:58Z"}},
        "vite": {"versions": {"8.3.4": npm_version(), "8.3.5": npm_version()}, "time": {}},
    })
    monkeypatch.setattr(checks, "Registries", lambda: reg)
    real_options = checks.Options
    monkeypatch.setattr(checks, "Options", lambda **kw: real_options(now=NOW, **kw))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def action_text():
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as fh:
        return fh.read()


def run_scripts(text):
    scripts = []
    for line in text.splitlines():
        match = re.match(r"^[ ]+run: (.+)$", line)
        if match:
            scripts.append(match.group(1))
            assert "${{" not in match.group(1)
    assert scripts, "action.yml has no run scripts"
    return scripts


@pytest.mark.parametrize("args,expected", [
    ("diff", ["diff"]),
    ("diff --base main", ["diff", "--base", "main"]),
    ("diff --base v1.2 --head v1.3 package-lock.json",
     ["diff", "--base", "v1.2", "--head", "v1.3", "package-lock.json"]),
    ("compare old/package-lock.json new/package-lock.json",
     ["compare", "old/package-lock.json", "new/package-lock.json"]),
    ("compare a.txt b.txt --as requirements.txt",
     ["compare", "a.txt", "b.txt", "--as", "requirements.txt"]),
    ('compare "old file.json" "new file.json"',
     ["compare", "old file.json", "new file.json"]),
    ("compare 'old file.json' 'new file.json'",
     ["compare", "old file.json", "new file.json"]),
    (r"compare old\ file.json new\ file.json",
     ["compare", "old file.json", "new file.json"]),
    ("compare examples/npm/old/package-lock.json examples/npm/new/package-lock.json",
     ["compare", "examples/npm/old/package-lock.json", "examples/npm/new/package-lock.json"]),
])
def test_supported_cli_words(args, expected):
    argv = action.build_argv(args, "high", "7")
    assert argv[:len(expected)] == expected
    assert argv[len(expected):] == ["--fail-on", "high", "--cooldown", "7"]


def test_quotes_survive_parsing_and_action_flags_win():
    argv = action.build_argv(
        'compare "old file.json" "new file.json" --as requirements.txt --format json --fail-on never --cooldown 1',
        "medium", "2.5")
    ns = build_parser().parse_args(argv)
    assert (ns.cmd, ns.old, ns.new, ns.as_name, ns.format) == (
        "compare", "old file.json", "new file.json", "requirements.txt", "json")
    assert ns.fail_on == "medium"
    assert ns.cooldown == 2.5


@pytest.mark.parametrize("args,expected", [
    ("diff; touch pwned", ["diff;", "touch", "pwned"]),
    ("diff && touch pwned", ["diff", "&&", "touch", "pwned"]),
    ("diff || touch pwned", ["diff", "||", "touch", "pwned"]),
    ("diff | sh", ["diff", "|", "sh"]),
    ("$(touch pwned)", ["$(touch", "pwned)"]),
    ("`touch pwned`", ["`touch", "pwned`"]),
    ("diff $HOME", ["diff", "$HOME"]),
    ("diff *.json", ["diff", "*.json"]),
    ("diff ~/lock.json", ["diff", "~/lock.json"]),
    ("diff # not-a-comment", ["diff", "#", "not-a-comment"]),
    ("diff\ntouch pwned", ["diff", "touch", "pwned"]),
    ('diff "a;$(whoami)"', ["diff", "a;$(whoami)"]),
    ("diff --base \"$(touch pwned)\"", ["diff", "--base", "$(touch pwned)"]),
])
def test_shell_metacharacters_stay_literal(args, expected):
    argv = action.build_argv(args, "high", "7")
    assert argv[:len(expected)] == expected


def test_globs_are_not_expanded(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    argv = action.build_argv("diff *.json", "high", "7")
    assert argv[1] == "*.json"
    assert "a.json" not in argv and "b.json" not in argv


def test_unmatched_quote_is_usage_error_and_does_not_call_cli(capsys, monkeypatch):
    monkeypatch.setattr(action, "cli_main", lambda argv: pytest.fail(f"cli called with {argv}"))
    monkeypatch.setenv(action.ARGS_ENV, 'compare "unterminated')
    assert action.main() == 2
    assert "could not parse args" in capsys.readouterr().err


def test_fail_on_and_cooldown_are_single_arguments(capsys, monkeypatch):
    fail_on = 'high"; touch pwned; echo "'
    cooldown = '7" || touch pwned #'
    assert action.build_argv("diff", fail_on, cooldown) == [
        "diff", "--fail-on", fail_on, "--cooldown", cooldown]
    monkeypatch.setenv(action.ARGS_ENV, "diff")
    monkeypatch.setenv(action.FAIL_ON_ENV, fail_on)
    monkeypatch.setenv(action.COOLDOWN_ENV, cooldown)
    assert action.main() == 2
    err = capsys.readouterr().err
    assert fail_on in err
    assert err.count("pwned") == 1


def test_defaults_when_env_is_unset(monkeypatch):
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(action, "cli_main", fake)
    monkeypatch.delenv(action.ARGS_ENV, raising=False)
    monkeypatch.delenv(action.FAIL_ON_ENV, raising=False)
    monkeypatch.delenv(action.COOLDOWN_ENV, raising=False)
    assert action.main() == 0
    assert seen["argv"] == ["diff", "--fail-on", "high", "--cooldown", "7"]


def test_compare_quoted_paths_with_spaces(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "lock files"
    folder.mkdir()
    old, new = folder / "old lock.json", folder / "new lock.json"
    old.write_text(lockv3({"vite": "8.3.4"}))
    new.write_text(lockv3({"vite": "8.3.5"}))
    monkeypatch.setenv(action.ARGS_ENV, "compare " + shlex.join([str(old), str(new), "--as", "package-lock.json"]))
    monkeypatch.setenv(action.FAIL_ON_ENV, "high")
    monkeypatch.setenv(action.COOLDOWN_ENV, "7")
    assert action.main() == 0
    assert "vite 8.3.4 -> 8.3.5" in capsys.readouterr().out


def test_default_diff_reports_findings(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "package-lock.json").write_text(lockv3({"axios": "1.14.0", "vite": "8.3.4"}))
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "package-lock.json").write_text(lockv3({"axios": "1.14.1", "vite": "8.3.5"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(action.ARGS_ENV, raising=False)
    monkeypatch.setenv(action.FAIL_ON_ENV, "high")
    monkeypatch.setenv(action.COOLDOWN_ENV, "7")
    assert action.main() == 1
    out = capsys.readouterr().out
    assert "axios 1.14.0 -> 1.14.1" in out
    assert "vite 8.3.4 -> 8.3.5" in out


def test_shipped_script_does_not_evaluate_untrusted_inputs(tmp_path):
    sentinel = tmp_path / "pwned"
    assert re.fullmatch(r"[A-Za-z0-9_./+-]+", str(sentinel))
    payload_args = f"diff --base $(touch {sentinel})"
    payload_fail = f"$(touch {sentinel})"
    payload_cool = f'7" || touch {sentinel} #'
    old = (f'python3 -m bumprisk {payload_args} --fail-on "{payload_fail}" '
           f'--cooldown "{payload_cool}"')
    control = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", old],
        capture_output=True, text=True)
    assert sentinel.is_file(), control.stderr
    sentinel.unlink()

    script = run_scripts(action_text())[-1]
    assert script == "python3 -m bumprisk.action"
    env = os.environ.copy()
    env.update({
        action.ARGS_ENV: payload_args,
        action.FAIL_ON_ENV: payload_fail,
        action.COOLDOWN_ENV: payload_cool,
    })
    fixed = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        env=env, capture_output=True, text=True)
    assert not sentinel.exists()
    assert fixed.returncode != 0
    assert payload_fail in fixed.stderr


def test_home_and_command_substitution_reach_cli_literally(capsys, monkeypatch):
    monkeypatch.setenv(action.ARGS_ENV, 'diff --base "$HOME"')
    monkeypatch.setenv(action.FAIL_ON_ENV, "$HOME")
    monkeypatch.setenv(action.COOLDOWN_ENV, "7")
    assert action.main() == 2
    err = capsys.readouterr().err
    assert "$HOME" in err
    assert os.environ["HOME"] not in err


def test_entrypoint_source_does_not_evaluate_strings():
    with open(os.path.join(ROOT, "src", "bumprisk", "action.py"), encoding="utf-8") as fh:
        src = fh.read()
    for banned in ("eval(", "exec(", "os.system", "subprocess", "shell=True", "bash -c", "sh -c"):
        assert banned not in src


def test_action_yml_passes_inputs_only_through_env():
    text = action_text()
    for line in text.splitlines():
        if "${{" in line:
            assert re.match(r"^[ ]+[A-Z0-9_]+:[ ]+\$\{\{.*\}\}[ ]*$", line), line
    scripts = run_scripts(text)
    assert scripts == [_INSTALL_RUN, "python3 -m bumprisk.action"]
    for script in scripts:
        assert "eval" not in script
        assert "bash -c" not in script
        assert "sh -c" not in script
    assert f"{action.ARGS_ENV}: ${{{{ inputs.args }}}}" in text
    assert f"{action.FAIL_ON_ENV}: ${{{{ inputs['fail-on'] }}}}" in text
    assert f"{action.COOLDOWN_ENV}: ${{{{ inputs.cooldown }}}}" in text
    assert "BUMPRISK_ACTION_PATH: ${{ github.action_path }}" in text
    joined = "\n".join(scripts)
    assert "inputs." not in joined


def test_marketplace_metadata():
    text = action_text()
    name = re.search(r"(?m)^name: (\S+)\s*$", text)
    description = re.search(r'(?m)^description: "(.*)"\s*$', text)
    icon = re.search(r"(?m)^  icon: (\S+)\s*$", text)
    color = re.search(r"(?m)^  color: (\S+)\s*$", text)
    assert name and name.group(1) == "bumprisk"
    assert description, "top-level description must be a quoted scalar"
    assert len(description.group(1)) < 125
    assert icon and icon.group(1) in _MARKETPLACE_ICONS
    assert icon.group(1) not in _OMITTED_ICONS
    assert color and color.group(1) in _BRAND_COLORS
    assert re.search(r"(?m)^author: \S", text)
    assert re.search(r"(?m)^  using: composite\s*$", text)
    assert not os.path.exists(os.path.join(ROOT, "action.yaml"))
    extras = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".venv", "node_modules"}]
        for filename in filenames:
            if filename in ("action.yml", "action.yaml") and os.path.abspath(dirpath) != ROOT:
                extras.append(os.path.join(dirpath, filename))
    assert extras == []


def test_license_stays_agpl_with_commercial_option():
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
        license_text = fh.read(80)
    assert license_text.startswith("                    GNU AFFERO GENERAL PUBLIC LICENSE")
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        project = fh.read()
    assert 'license = "AGPL-3.0-or-later"' in project
    assert f'version = "{__version__}"' in project
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert "Commercial licenses without the AGPL obligations" in readme
    assert "hamarshehmhmd/bumprisk@v0.1.1" in readme


def test_ci_checks_untrusted_action_inputs():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        text = fh.read()
    assert "uses: ./" in text
    assert "bumprisk-pwned" in text
    assert 'args: compare examples/npm/old/package-lock.json examples/npm/new/package-lock.json' in text
    assert "action input was executed by the shell" in text
