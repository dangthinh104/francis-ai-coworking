#!/bin/sh
# What .github/workflows/tests.yml runs, on this machine: the suite with the Python found here,
# then on Linux with Python 3.9 and 3.12 in containers, each on a fresh clone of the commit checked out.
# Not covered: Windows with Python 3.9 and 3.12 unless that is the Python found here.
# Needs git, python and Docker. Usage: sh local-check.sh, from the root of the repository.
set -eu

if [ -n "$(git status --porcelain)" ]; then
  echo "local-check: commit or set aside the changes first: the containers test the commit, not the working tree" >&2
  exit 2
fi
if git rev-parse -q --verify origin/main >/dev/null && ! git merge-base --is-ancestor origin/main HEAD; then
  echo "local-check: merge origin/main first: a pull request is judged as merged with it" >&2
  exit 2
fi
commit=$(git rev-parse HEAD)
store=$(cd "$(git rev-parse --git-common-dir)" && pwd -W 2>/dev/null || pwd)
python=$(command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null && echo python3 || echo python)

failed=""
here=$($python --version)
echo "== here: $here, commit $commit"
room=$(mktemp -d)
status=0
{
  $python -m venv "$room/venv"
  if [ -x "$room/venv/bin/python" ]; then inner="$room/venv/bin/python"; else inner="$room/venv/Scripts/python.exe"; fi
  "$inner" -m pip install -q -r requirements-dev.txt
  "$inner" -m pytest tests -q -p no:cacheprovider
} > "$room/log" 2>&1 || status=$?
tail -n 3 "$room/log"
rm -rf "$room"
[ "$status" -eq 0 ] || failed="$failed here"

for version in 3.9 3.12; do
  audit=":"
  [ "$version" = "3.12" ] && audit="pip install -q --root-user-action=ignore pip-audit==2.10.1
    pip-audit -r requirements-dev.txt"
  echo "== Linux, Python $version"
  MSYS_NO_PATHCONV=1 docker run --rm -v "$store:/store.git:ro" "python:$version" sh -ec "
    git config --global --add safe.directory '*'
    git clone -q /store.git /work
    cd /work
    git checkout -q $commit
    git config user.email check@example.invalid
    git config user.name check
    pip install -q --root-user-action=ignore -r requirements-dev.txt
    $audit
    status=0
    python -m pytest tests -q -p no:cacheprovider > /tmp/suite.log 2>&1 || status=\$?
    tail -n 3 /tmp/suite.log
    exit \$status
  " || failed="$failed linux-$version"
done

if [ -n "$failed" ]; then
  echo "local-check: FAILED:$failed" >&2
  exit 1
fi
echo "local-check: passed with $here here and on Linux with Python 3.9 and 3.12, commit $commit"
