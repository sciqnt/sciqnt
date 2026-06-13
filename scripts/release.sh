#!/usr/bin/env bash
# Release one package — the whole per-package publish is this one command.
#
#   scripts/release.sh degiro 0.2.0      # → tags sciqnt-degiro/v0.2.0, pushes
#   scripts/release.sh schema 1.0.0
#
# The push triggers .github/workflows/release.yml, which resolves the tag to
# its package dir, builds the wheel + sdist, and publishes to PyPI via Trusted
# Publishing (no tokens). That's it — tag in, package on PyPI out.
set -euo pipefail
cd "$(dirname "$0")/.."

slug="${1:?usage: release.sh <package-slug> <version>   e.g. release.sh degiro 0.2.0}"
version="${2:?need a version, e.g. 0.2.0}"
dist="sciqnt-${slug}"

# Verify the package exists and bump its version to match the tag.
pp=$(grep -rl "^name = \"${dist}\"" core/*/pyproject.toml modules/*/pyproject.toml) \
  || { echo "no package named ${dist}"; exit 1; }
sed -i.bak -E "s/^version = \".*\"/version = \"${version}\"/" "$pp" && rm -f "${pp}.bak"
echo "bumped ${dist} → ${version} in ${pp}"

git add "$pp"
git commit -m "release: ${dist} ${version}" >/dev/null
git tag "${dist}/v${version}"
echo "tagged ${dist}/v${version}"
echo "→ push to publish:  git push && git push --tags"
