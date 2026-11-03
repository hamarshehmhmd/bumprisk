#!/bin/sh
# Builds a throwaway git repo with a "Dependabot-style" lockfile change for the demo.
set -eu
D=${1:-/tmp/shop-web}
rm -rf "$D" && mkdir -p "$D" && cd "$D"
git init -q -b main && git config user.email demo@example.com && git config user.name demo
lock() {
python3 - "$@" <<'PY'
import json, sys
deps = dict(a.split("=") for a in sys.argv[1:])
pk = {"": {"name": "shop-web", "version": "1.0.0"}}
for n, v in deps.items():
    pk[f"node_modules/{n}"] = {"version": v, "resolved": f"https://registry.npmjs.org/{n}/-/{n}-{v}.tgz"}
print(json.dumps({"name": "shop-web", "lockfileVersion": 3, "requires": True, "packages": pk}, indent=2))
PY
}
lock typescript=5.9.3 nx=24.0.2 axios=0.34.0 react=19.1.0 > package-lock.json
git add . && git commit -qm "initial"
git checkout -qb deps/weekly
lock typescript=6.0.3 nx=24.0.3 axios=0.35.0 react=19.1.0 esbuild=0.28.2 > package-lock.json
git commit -qam "chore(deps): weekly bump"
