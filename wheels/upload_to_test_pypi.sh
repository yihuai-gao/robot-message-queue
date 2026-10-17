#!/usr/bin/env bash
set -euo pipefail
export ROBOTMQ_REPOSITORY_URL=https://test.pypi.org/legacy/
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/upload_to_pypi.sh" "$@"
