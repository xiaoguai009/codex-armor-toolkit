#!/bin/bash
# Finder may start this file from an unrelated working directory.
SCRIPT_PATH=${BASH_SOURCE[0]}
SCRIPT_DIR=${SCRIPT_PATH%/*}
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then SCRIPT_DIR=.; fi
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR" && pwd -P) || exit 2
exec /bin/bash "$ROOT/macos/launch.sh" --restore "$@"
