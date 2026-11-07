"""GitHub Action entrypoint.

The composite action passes inputs only as environment variables. This module
turns those values into an argv list and calls the CLI. It does not run a shell.

BUMPRISK_ARGS is split with POSIX shlex rules: quotes and backslashes group
words, which is what a CLI user expects for paths that contain spaces.
Parameter expansion, command substitution, globs, pipes, and other shell
syntax stay literal text.
"""
from __future__ import annotations

import os
import shlex
import sys

from .cli import main as cli_main

ARGS_ENV = "BUMPRISK_ARGS"
FAIL_ON_ENV = "BUMPRISK_FAIL_ON"
COOLDOWN_ENV = "BUMPRISK_COOLDOWN"

DEFAULT_ARGS = "diff"
DEFAULT_FAIL_ON = "high"
DEFAULT_COOLDOWN = "7"


class ArgsError(Exception):
    """BUMPRISK_ARGS is not a finished quoted command line."""


def build_argv(args: str, fail_on: str, cooldown: str) -> list[str]:
    """Split ``args`` like a command line and append the action flags.

    ``--fail-on`` and ``--cooldown`` are appended last, so the action inputs
    win when the same option also appears in ``args``. The previous action
    appended those flags after the free-form arguments too.
    """
    try:
        argv = shlex.split(args, posix=True)
    except ValueError as exc:
        raise ArgsError(f"could not parse args: {exc}") from exc
    argv.extend(["--fail-on", fail_on, "--cooldown", cooldown])
    return argv


def argv_from_env(env=None) -> list[str]:
    env = os.environ if env is None else env
    return build_argv(
        env.get(ARGS_ENV, DEFAULT_ARGS),
        env.get(FAIL_ON_ENV, DEFAULT_FAIL_ON),
        env.get(COOLDOWN_ENV, DEFAULT_COOLDOWN),
    )


def main(env=None) -> int:
    try:
        argv = argv_from_env(env)
    except ArgsError as exc:
        print(f"bumprisk: {exc}", file=sys.stderr)
        return 2
    try:
        return cli_main(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
