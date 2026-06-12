#!/usr/bin/env bash
# Personal-data gate — release-plan step 1, enforced forever.
#
# Scans GIT-TRACKED files (what would actually ship) for identity strings
# that must never reach a public repo: real account labels, family names,
# personal emails, broker account ids, machine paths/hostnames, wallet
# addresses. Runs at the end of ./run_tests.sh and as a CI job after
# publish. Untracked local files (.env credentials, caches) are out of
# scope here — git's tracking boundary IS the publish boundary.
#
# NOT in scope (intentionally public): "DavideGCosta" — the owner's GitHub
# identity (LICENSE copyright, user-zero lines). The "DavideCosta" pattern
# below does NOT match it (no G).
#
# Exit 0 = clean; exit 1 = hits printed. Approved synthetic stand-ins:
# AccountA/B, AliceExample, account id 10000001.
set -u
cd "$(dirname "$0")/.."

# "cs:" prefix = case-SENSITIVE pattern. (grep -i makes [A-Z] classes
# case-insensitive too — 'Gina[A-Z]' would match "original"; bug found
# the hard way 2026-06-12.)
PATTERNS=(
  "DavideCosta"                  # real account labels (also catches …Trading)
  "Davide Costa"
  "cs:Gina([^a-zA-Z]|[A-Z]|$)"   # GinaCosta / degiro:Gina — NOT "original"
  "davidecosta889"               # personal emails
  "@icloud.com"
  "0x2f2287df"                   # polymarket wallet
  "61016555"                     # real Degiro int_account ids
  "61013790"
  "cunkys"                       # machine user / paths
  "Cunkyss-MacBook"              # hostname
)

fail=0
for pat in "${PATTERNS[@]}"; do
  flags="-Eril"
  case "$pat" in cs:*) flags="-Erl"; pat="${pat#cs:}";; esac
  hits=$(git grep $flags "$pat" -- . ":!scripts/check_personal_data.sh" \
         2>/dev/null)
  if [ -n "$hits" ]; then
    echo "PERSONAL DATA: pattern '$pat' found in TRACKED files:"
    echo "$hits" | sed 's/^/    /'
    fail=1
  fi
done

# Credentials must never be tracked — only the .example templates.
envs=$(git ls-files | grep -E "(^|/)\.env$")
if [ -n "$envs" ]; then
  echo "CREDENTIALS: .env file(s) are git-tracked:"
  echo "$envs" | sed 's/^/    /'
  fail=1
fi

if [ "$fail" -eq 1 ]; then
  echo
  echo "Scrub before committing — see research/release-plan.md step 1."
  exit 1
fi
echo "personal-data check: clean (tracked files)"
