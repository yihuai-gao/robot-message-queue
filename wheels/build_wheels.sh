#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root_dir"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Commit tracked changes before building release wheels." >&2
    exit 1
fi

commit=$(git rev-parse HEAD)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml)
architectures=("$@")
if ((${#architectures[@]} == 0)); then
    architectures=("$(uname -m)")
fi
mkdir -p build wheels/wheelhouse
staging=$(mktemp -d "$root_dir/build/release.XXXXXX")
container=""
cleanup() {
    if [[ -n "$container" ]]; then docker rm "$container" >/dev/null; fi
}
trap cleanup EXIT

for architecture in "${architectures[@]}"; do
    case "$architecture" in
        x86_64) platform=linux/amd64 ;;
        aarch64|arm64) architecture=aarch64; platform=linux/arm64 ;;
        *) echo "Unsupported architecture: $architecture" >&2; exit 1 ;;
    esac
    image="robotmq:release-${commit:0:12}-$architecture"
    git archive HEAD | docker build --platform "$platform" \
        --build-arg "ROBOTMQ_COMMIT=$commit" \
        --file "wheels/Dockerfile.$architecture" --tag "$image" -
    container=$(docker create --platform "$platform" "$image")
    docker cp "$container:/wheelhouse/." "$staging/"
    docker rm "$container" >/dev/null
    container=""
done

shopt -s nullglob
wheels=("$staging"/robotmq-"$version"-*.whl)
expected=$((7 * ${#architectures[@]}))
if ((${#wheels[@]} != expected)); then
    echo "Expected $expected release wheels, found ${#wheels[@]} in $staging" >&2
    exit 1
fi
printf 'commit=%s\nversion=%s\narchitectures=%s\n' \
    "$commit" "$version" "${architectures[*]}" > "$staging/BUILD_INFO"
(cd "$staging" && sha256sum -- *.whl > SHA256SUMS)
destination="$root_dir/wheels/wheelhouse/$version"
if [[ -e "$destination" ]]; then
    mv "$destination" "$root_dir/build/previous-wheels-$version-$(date +%s)"
fi
mv "$staging" "$destination"
echo "Release wheels: $destination"
echo "Check: bash wheels/upload_to_pypi.sh --check"
echo "Publish: bash wheels/upload_to_pypi.sh"

