#!/bin/sh
# Weekly snapshot of boxy's logins + settings (Spotify pairing, YouTube tokens,
# Kodi/skin/add-on settings). Goes to a USB drive labelled BOXYBACKUP when one
# is plugged in, otherwise to /var/backups/boxy on the SD card. Keeps the
# newest $KEEP archives.
set -eu
USER_HOME=/home/barbara
KEEP=6
LABEL=BOXYBACKUP
MNT=/mnt/boxy-backup
DEST=/var/backups/boxy
mounted=""

dev=$(blkid -L "$LABEL" 2>/dev/null || true)
if [ -n "$dev" ]; then
  mkdir -p "$MNT"
  if mountpoint -q "$MNT" || mount "$dev" "$MNT"; then
    DEST="$MNT/boxy"; mounted=1
  fi
fi
mkdir -p "$DEST"

out="$DEST/boxy-$(date +%Y%m%d-%H%M).tar.gz"
tar -czf "$out.tmp" -C / \
  --exclude="home/barbara/.kodi/userdata/Thumbnails" \
  --exclude="home/barbara/.kodi/userdata/Database/Textures*.db" \
  --exclude="home/barbara/.kodi/userdata/addon_data/*/cache*" \
  --exclude="home/barbara/.kodi/userdata/addon_data/plugin.audio.spotify/boxy_snapshots" \
  --exclude="home/barbara/.kodi/userdata/addon_data/plugin.audio.spotify/spotty-cache/files" \
  --exclude="*.sqlite-wal" \
  "${USER_HOME#/}/.kodi/userdata" \
  etc/systemd/system/boxy-splash.service etc/systemd/system/boxy-backup.service \
  etc/systemd/system/boxy-backup.timer var/lib/kodi-siri-bridge \
  2>/dev/null || [ $? -eq 1 ]          # 1 = a file changed while reading: fine
mv "$out.tmp" "$out"

ls -1t "$DEST"/boxy-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup: $out ($(du -h "$out" | cut -f1))"
sync
[ -n "$mounted" ] && umount "$MNT" || true
