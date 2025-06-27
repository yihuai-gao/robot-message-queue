#! /bin/bash

set -e

pip install twine
twine upload --repository-url https://test.pypi.org/legacy/ wheels/wheelhouse/* --verbose