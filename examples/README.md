# Example lockfiles (test fixtures)

These files reproduce real supply-chain incidents (the March 31, 2026 axios compromise that pulled in
`plain-crypto-js@4.2.1`, and the chalk/debug releases) so bumprisk's tests and demo can show what it catches.

They are **not installable**: they're named `package-lock.fixture.json` rather than `package-lock.json`, and they
carry no `resolved` tarball URLs or integrity hashes. No package code is vendored anywhere in this repo. Never
copy them into a real project.
