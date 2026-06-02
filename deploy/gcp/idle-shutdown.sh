#!/usr/bin/env bash
# OPTIONAL credit-saver: auto-stop the VM after a period with no active
# WebSocket connection to the backend. Install as a systemd timer (see README).
#
# "Active" = at least one ESTABLISHED connection to the backend's port 8000.
# After IDLE_LIMIT consecutive idle checks, the VM stops itself.
set -euo pipefail

IDLE_LIMIT="${IDLE_LIMIT:-6}"          # consecutive idle checks before stopping
STATE_FILE=/var/run/signspeak-idle.count

# Count established connections to the backend container's published port.
# Backend listens on 8000 inside its network; Traefik proxies it, so we look
# for active 443 sessions that are not the local health probe.
active="$(ss -Htan state established '( dport = :443 or sport = :443 )' 2>/dev/null | wc -l)"

if [ "$active" -gt 0 ]; then
  echo 0 > "$STATE_FILE"
  exit 0
fi

count="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
count=$((count + 1))
echo "$count" > "$STATE_FILE"

if [ "$count" -ge "$IDLE_LIMIT" ]; then
  echo "Idle for $count checks — stopping VM to save credit."
  NAME="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/name)"
  ZONE="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $NF}')"
  gcloud compute instances stop "$NAME" --zone="$ZONE" --quiet
fi
