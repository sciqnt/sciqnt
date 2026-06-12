#!/usr/bin/env bash
# Run every unit's conformance tests. Each test file puts its own module on the
# path, so this works without installing. Used standalone and by the `maintenance`
# skill's --fix pass (fixes must leave tests green).
set -uo pipefail
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

fail=0
for d in modules/*/tests core/tests; do
  [ -d "$d" ] || continue
  echo "== $d =="
  "$PY" -m unittest discover -s "$d" -p 'test_*.py' -t "$d" 2>&1 \
       | grep -vE 'NotOpenSSLWarning|warnings.warn'
  # pipefail propagates unittest's exit code (grep can't mask test failures)
  rc=${PIPESTATUS[0]}
  [ "$rc" -ne 0 ] && fail=1
done

# Personal-data gate (release-plan step 1) — tracked files must stay clean.
./scripts/check_personal_data.sh || fail=1

if [ "$fail" -eq 0 ]; then
  echo "ALL TESTS PASS"
else
  echo "TESTS FAILED"
fi
exit "$fail"
