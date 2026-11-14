#!/bin/sh
# Packs the integration with the built panel into notification_journal.zip, with the given version in its manifest.
set -eu
version="$1"
cd "$(dirname "$0")/.."
component=custom_components/notification_journal
test -s "${component}/frontend/panel.js" || { echo "build the panel first" >&2; exit 1; }
jq --arg version "${version}" '.version = $version' "${component}/manifest.json" > manifest.tmp
mv manifest.tmp "${component}/manifest.json"
rm -f notification_journal.zip
cd "${component}"
zip -r -q ../../notification_journal.zip . -x '__pycache__/*'
