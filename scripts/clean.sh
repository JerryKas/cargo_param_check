#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build dist *.spec
echo "Clean done"

