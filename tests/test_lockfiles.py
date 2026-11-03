import json

import pytest

from bumprisk.lockfiles import LockfileError, NPM, PYPI, is_lockfile, kind_of, parse


def test_kinds():
    assert kind_of("a/b/package-lock.json") == "npm-lock"
    assert kind_of("npm-shrinkwrap.json") == "npm-lock"
    assert kind_of("yarn.lock") == "yarn"
    assert kind_of("pnpm-lock.yaml") == "pnpm"
    assert kind_of("uv.lock") == kind_of("poetry.lock") == kind_of("pdm.lock") == "toml-lock"
    assert kind_of("Pipfile.lock") == "pipfile"
    assert kind_of("requirements-dev.txt") == kind_of("requirements/base.txt") == "requirements"
    assert kind_of("constraints.txt") == "requirements"
    assert not is_lockfile("package.json")
    assert not is_lockfile("README.txt")


def test_npm_lock_v3():
    text = json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "app"},
        "node_modules/axios": {"version": "1.14.0", "resolved": "https://registry.npmjs.org/axios/-/axios-1.14.0.tgz"},
        "node_modules/@scope/pkg": {"version": "2.0.0"},
        "node_modules/a/node_modules/ms": {"version": "2.0.0"},
        "node_modules/ms": {"version": "2.1.3"},
        "node_modules/local": {"resolved": "packages/local", "link": True},
        "node_modules/gitdep": {"version": "1.0.0", "resolved": "git+ssh://git@github.com/x/y.git#abc"},
        "node_modules/alias": {"name": "real-pkg", "version": "3.0.0"},
        "packages/local": {"version": "0.0.0"},
    }})
    got = parse(text, "package-lock.json")
    assert got[(NPM, "axios")] == {"1.14.0"}
    assert got[(NPM, "@scope/pkg")] == {"2.0.0"}
    assert got[(NPM, "ms")] == {"2.0.0", "2.1.3"}
    assert got[(NPM, "real-pkg")] == {"3.0.0"}
    assert (NPM, "local") not in got and (NPM, "gitdep") not in got


def test_npm_lock_v1():
    text = json.dumps({"lockfileVersion": 1, "dependencies": {
        "left-pad": {"version": "1.3.0", "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",
                     "dependencies": {"ms": {"version": "2.0.0"}}},
        "aliased": {"version": "npm:real@1.0.0"},
        "fromgit": {"version": "github:x/y#abc"},
    }})
    got = parse(text, "package-lock.json")
    assert got == {(NPM, "left-pad"): {"1.3.0"}, (NPM, "ms"): {"2.0.0"}, (NPM, "real"): {"1.0.0"}}


YARN_CLASSIC = '''# yarn lockfile v1


"@babel/core@^7.0.0", "@babel/core@^7.1.0":
  version "7.24.0"
  resolved "https://registry.yarnpkg.com/@babel/core/-/core-7.24.0.tgz#abc"
  dependencies:
    debug "^4.1.0"

debug@^4.1.0:
  version "4.4.1"
  resolved "https://registry.yarnpkg.com/debug/-/debug-4.4.1.tgz"

mylib@git+https://github.com/x/mylib.git:
  version "1.0.0"
  resolved "git+https://github.com/x/mylib.git#deadbeef"
'''

YARN_BERRY = '''__metadata:
  version: 8
  cacheKey: 10c0

"axios@npm:^1.14.0":
  version: 1.14.1
  resolution: "axios@npm:1.14.1"
  dependencies:
    plain-crypto-js: "npm:^4.2.1"
  languageName: node

"@types/node@npm:^22, @types/node@npm:^22.1":
  version: 22.5.0
  resolution: "@types/node@npm:22.5.0"

"app@workspace:.":
  version: 0.0.0-use.local
  resolution: "app@workspace:."
'''


def test_yarn_classic():
    got = parse(YARN_CLASSIC, "yarn.lock")
    assert got == {(NPM, "@babel/core"): {"7.24.0"}, (NPM, "debug"): {"4.4.1"}}


def test_yarn_berry():
    got = parse(YARN_BERRY, "yarn.lock")
    assert got == {(NPM, "axios"): {"1.14.1"}, (NPM, "@types/node"): {"22.5.0"}}


PNPM9 = '''lockfileVersion: '9.0'

importers:
  .:
    dependencies:
      axios:
        specifier: ^1.14.0
        version: 1.14.0

packages:

  '@esbuild/linux-x64@0.25.0':
    resolution: {integrity: sha512-x}
    cpu: [x64]

  axios@1.14.0:
    resolution: {integrity: sha512-y}

snapshots:

  axios@1.14.0:
    dependencies:
      follow-redirects: 1.15.11

  react-dom@18.3.1(react@18.3.1):
    dependencies:
      react: 18.3.1
'''

PNPM6 = '''lockfileVersion: '6.0'

packages:

  /axios@1.13.0:
    resolution: {integrity: sha512-z}

  /@types/node@22.5.0:
    resolution: {integrity: sha512-w}
'''


def test_pnpm_v9():
    got = parse(PNPM9, "pnpm-lock.yaml")
    assert got == {(NPM, "@esbuild/linux-x64"): {"0.25.0"}, (NPM, "axios"): {"1.14.0"},
                   (NPM, "react-dom"): {"18.3.1"}}


def test_pnpm_v6():
    got = parse(PNPM6, "pnpm-lock.yaml")
    assert got == {(NPM, "axios"): {"1.13.0"}, (NPM, "@types/node"): {"22.5.0"}}


def test_requirements():
    text = """# comment
Requests==2.31.0 \\
    --hash=sha256:abc
urllib3[socks]==2.2.3 ; python_version >= "3.8"
-r other.txt
-e .
django>=4.2
zope.interface===6.0
git+https://github.com/x/y.git
numpy==2.1.0  # pinned
"""
    got = parse(text, "requirements.txt")
    assert got == {(PYPI, "requests"): {"2.31.0"}, (PYPI, "urllib3"): {"2.2.3"},
                   (PYPI, "zope-interface"): {"6.0"}, (PYPI, "numpy"): {"2.1.0"}}


def test_uv_lock_skips_local_project():
    text = '''version = 1

[[package]]
name = "myapp"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Typing_Extensions"
version = "4.12.2"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "fromgit"
version = "1.0"
source = { git = "https://github.com/x/y?rev=abc" }
'''
    assert parse(text, "uv.lock") == {(PYPI, "typing-extensions"): {"4.12.2"}}


def test_poetry_lock():
    text = '''[[package]]
name = "requests"
version = "2.32.3"

[[package]]
name = "localpkg"
version = "0.1.0"

[package.source]
type = "directory"
url = "../localpkg"
'''
    assert parse(text, "poetry.lock") == {(PYPI, "requests"): {"2.32.3"}}


def test_pipfile_lock():
    text = json.dumps({"default": {"requests": {"version": "==2.32.3"}, "x": {"git": "https://..."}},
                       "develop": {"pytest": {"version": "==8.3.0"}}})
    assert parse(text, "Pipfile.lock") == {(PYPI, "requests"): {"2.32.3"}, (PYPI, "pytest"): {"8.3.0"}}


def test_empty_and_errors():
    assert parse("", "package-lock.json") == {}
    with pytest.raises(LockfileError):
        parse("{not json", "package-lock.json")
    with pytest.raises(LockfileError):
        parse("x", "Gemfile.lock")
