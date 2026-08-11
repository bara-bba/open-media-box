#!/bin/bash
# Reference / verification script for the Dispatcharr service on the
# *arr Docker host ("servarr", separate machine from boxy — this is IPTV
# management for Jellyfin Live TV + Kodi PVR, not part of boxy's own stack).
#
# This does NOT auto-patch compose.yaml: that file is hand-maintained and
# heavily commented (see docker-setup/compose.yaml on servarr), and a
# YAML-library rewrite would strip all of that. Instead this script prints
# the exact block to paste in by hand, and can verify/bring up the service
# once it's there.
#
# Usage:
#   ./setup-dispatcharr.sh block     # print the compose service block to add
#   ./setup-dispatcharr.sh up        # docker compose up -d dispatcharr
#   ./setup-dispatcharr.sh verify    # check container health + DNS resolution
#
# Run from ~/docker-setup/ on servarr (192.168.1.68).

set -euo pipefail

COMPOSE_BLOCK='  dispatcharr:
    image: ghcr.io/dispatcharr/dispatcharr:latest
    container_name: dispatcharr
    restart: unless-stopped
    environment:
      - DISPATCHARR_ENV=aio
      - REDIS_HOST=localhost
      - CELERY_BROKER_URL=redis://localhost:6379/0
      - DISPATCHARR_LOG_LEVEL=info
      - TZ=${TZ}
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ./dispatcharr:/data
    # 1.1.1.1 instead of the host default resolver: Italian ISP-level
    # anti-piracy DNS filtering (Piracy Shield) has been seen incorrectly
    # affecting legitimate broadcaster domains (mediapolis.rai.it) — see
    # README "Live TV" section. Cloudflare DNS sidesteps that reliably.
    dns:
      - 1.1.1.1
      - 1.0.0.1
    ports:
      - 9191:9191
    networks:
      servarrnetwork:
        ipv4_address: 172.39.0.10
    # NOTE: deliberately NOT routed via `network_mode: service:gluetun`.
    # Tried that — Rai (and likely other Italian broadcasters) blocks
    # known commercial VPN IP ranges outright regardless of exit country,
    # so IPTV traffic needs your real residential IP, not the VPN.'

case "${1:-}" in
  block)
    cat <<EOF
Paste this into docker-setup/compose.yaml as a new top-level service
(same indentation as other services, e.g. right after jellyseerr):

$COMPOSE_BLOCK

Also remove any "9191:9191" line you may have added to gluetun's ports —
not needed since dispatcharr isn't VPN-routed.

Then run: $0 up
EOF
    ;;
  up)
    docker compose up -d dispatcharr
    ;;
  verify)
    echo "--- container status ---"
    docker ps --filter name=dispatcharr
    echo "--- DNS resolution check (should NOT be 0.0.0.0) ---"
    docker exec dispatcharr sh -c "getent hosts mediapolis.rai.it || nslookup mediapolis.rai.it" 2>&1 || true
    echo "--- web UI reachability ---"
    curl -s -o /dev/null -w "HTTP:%{http_code}\n" http://localhost:9191 || true
    ;;
  *)
    echo "Usage: $0 {block|up|verify}"
    exit 1
    ;;
esac
