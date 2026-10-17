#!/usr/bin/env bash
set -euo pipefail

source_dir=/root/robot-message-queue
architecture=$(uname -m)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$source_dir/pyproject.toml")
mkdir -p /wheelhouse

for abi in cp38-cp38 cp39-cp39 cp310-cp310 cp311-cp311 cp312-cp312 cp313-cp313 cp314-cp314; do
    echo "=== Building and testing robotmq $version for $abi / $architecture ==="
    work="/build/$abi"
    mkdir -p "$work" "/raw/$abi" "/checks/$abi"
    cp -a "$source_dir/." "$work/"
    cp "$work/wheels/CMakeLists.txt" "$work/CMakeLists.txt"
    "/opt/python/$abi/bin/python" -m venv "/venvs/$abi"
    export PATH="/venvs/$abi/bin:$PATH"
    python -m pip install --disable-pip-version-check --upgrade pybind11 'setuptools>=64' wheel
    cd "$work"
    # The project's CMake build writes the extension into the source package.
    # Build it before wheel packaging collects package_data.
    python -m pip install --no-build-isolation --no-deps -e .
    python -m pip wheel --no-build-isolation --no-deps --wheel-dir "/raw/$abi" .
    auditwheel repair "/raw/$abi/robotmq-$version-$abi-linux_$architecture.whl" --wheel-dir /wheelhouse

    repaired=(/wheelhouse/robotmq-"$version"-"$abi"-*.whl)
    if ((${#repaired[@]} != 1)); then
        echo "Expected one repaired wheel for $abi" >&2
        exit 1
    fi
    "/opt/python/$abi/bin/python" -m venv "/testenvs/$abi"
    test_python="/testenvs/$abi/bin/python"
    "$test_python" -m pip install --disable-pip-version-check "${repaired[0]}" pytest pyzmq
    cp -a "$source_dir/tests" "/checks/$abi/tests"
    cd "/checks/$abi"
    "$test_python" -c 'import robotmq; assert "/testenvs/" in robotmq.__file__, robotmq.__file__; print("Testing installed wheel:", robotmq.__file__)'
    "$test_python" -m pytest tests -q --maxfail=1
done

/opt/python/cp312-cp312/bin/python -m venv /release-tools
/release-tools/bin/python -m pip install --disable-pip-version-check twine
/release-tools/bin/python -m twine check --strict /wheelhouse/*.whl
