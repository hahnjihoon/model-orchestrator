#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
export PYTHONUTF8=1
export PYTHONUNBUFFERED=1
training_python="${TRAIN_PYTHON:-$HOME/aiq-train/.venv/bin/python}"
if [[ ! -x "$training_python" ]]; then
    printf 'Training Python executable was not found: %s\n' "$training_python" >&2
    exit 1
fi
exec "$training_python" -u "$PWD/train.py" "$@"
