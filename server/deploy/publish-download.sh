#!/usr/bin/env bash
# Put a file (e.g. the Windows agent exe) on the server's /downloads page.
#
#   server/deploy/publish-download.sh path/to/pebble-agent.exe [user@host]
set -euo pipefail
FILE=$1
HOST=${2:-george@192.168.3.10}
NAME=$(basename "$FILE")
scp -q "$FILE" "$HOST:/tmp/$NAME"
ssh "$HOST" "sudo install -D -o pebble -g pebble -m 644 /tmp/$NAME /opt/pebble/server/instance/downloads/$NAME && rm /tmp/$NAME"
echo "Published: http://${HOST#*@}/downloads/$NAME"
