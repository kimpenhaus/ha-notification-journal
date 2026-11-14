#!/bin/sh
# The frontend integration needs the frontend wheel, which the test package does not bring;
# it is installed at the version the tested Home Assistant pins.
set -eu
pip install --no-cache-dir --disable-pip-version-check -q -r requirements-dev.txt
frontend="$(python -c 'import json, pathlib, homeassistant.components.frontend as f; print(json.loads((pathlib.Path(f.__file__).parent / "manifest.json").read_text())["requirements"][0])')"
pip install --no-cache-dir --disable-pip-version-check -q "${frontend}"
