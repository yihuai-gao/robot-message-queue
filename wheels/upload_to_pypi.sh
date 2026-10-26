#!/usr/bin/env bash
set -euo pipefail

if (($# > 1)) || [[ ${1:-} != "" && ${1:-} != --check ]]; then
    echo "Usage: $0 [--check]" >&2
    exit 1
fi
root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if ! git -C "$root_dir" diff --quiet || ! git -C "$root_dir" diff --cached --quiet; then
    echo "Commit tracked changes and rebuild release wheels before publishing." >&2
    exit 1
fi
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$root_dir/pyproject.toml")
release_dir="$root_dir/wheels/wheelhouse/$version"
if [[ ! -f "$release_dir/SHA256SUMS" || ! -f "$release_dir/BUILD_INFO" ]]; then
    echo "No completed release build for $version. Run wheels/build_wheels.sh first." >&2
    exit 1
fi
commit=$(git -C "$root_dir" rev-parse HEAD)
build_commit=$(sed -n 's/^commit=//p' "$release_dir/BUILD_INFO")
build_version=$(sed -n 's/^version=//p' "$release_dir/BUILD_INFO")
if [[ "$build_commit" != "$commit" || "$build_version" != "$version" ]]; then
    echo "Release build does not match the current commit and version. Run wheels/build_wheels.sh first." >&2
    exit 1
fi
cd "$release_dir"
sha256sum --check SHA256SUMS
shopt -s nullglob
wheels=(robotmq-"$version"-*.whl)
all_wheels=(*.whl)
expected=$(wc -l < SHA256SUMS)
if ((${#wheels[@]} == 0 || ${#wheels[@]} != ${#all_wheels[@]} || ${#wheels[@]} != expected)); then
    echo "Release directory contains an unexpected wheel set." >&2
    exit 1
fi

tools_dir="$root_dir/build/publish-venv"
if [[ ! -x "$tools_dir/bin/python" ]]; then
    "${ROBOTMQ_PYTHON:-python3}" -m venv "$tools_dir"
fi
if ! "$tools_dir/bin/python" -m twine --version >/dev/null 2>&1; then
    "$tools_dir/bin/python" -m pip install twine
fi
"$tools_dir/bin/python" -m twine check --strict "${wheels[@]}"
if [[ ${1:-} == --check ]]; then
    echo "Ready to publish ${#wheels[@]} wheels for robotmq $version."
    exit 0
fi
repository_args=()
if [[ -n ${ROBOTMQ_REPOSITORY_URL:-} ]]; then
    repository_args=(--repository-url "$ROBOTMQ_REPOSITORY_URL")
fi
"$tools_dir/bin/python" -m twine upload "${repository_args[@]}" "${wheels[@]}"
