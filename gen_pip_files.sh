#!/usr/bin/env bash

# Generate pip-style requirements and constraints files from the
# chromium-specific vpython3 spec.
grep 'name:' run_tests.vpython3 | \
    sed 's,  name: "infra/python/wheels/\(.*\)-\(py2_py3\|py3\)",\1,' \
    > pip_requirements.txt
grep --no-group-separator -A1 'name:' run_tests.vpython3 | \
    sed 's,  name: "infra/python/wheels/\(.*\)-\(py2_py3\|py3\)",\1,' | \
    sed 's,  version: "version:\(.*\)",==\1,' | tr -d '\n'  | sed 's,\(\.[0-9]\)\([a-z]\),\1\n\2,g' \
    > pip_constraints.txt

echo "Ready for install with pip"
echo "Example: pip3 install --requirement pip_requirements.txt --constraint pip_constraints.txt"
