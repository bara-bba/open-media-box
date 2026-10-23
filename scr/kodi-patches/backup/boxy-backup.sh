#!/bin/sh
# Weekly snapshot of boxy's logins + settings (Spotify pairing, YouTube tokens,
# Kodi/skin/add-on settings). Goes to the NAS over NFS
# (192.168.42.61:/mnt/main/backups/boxy, exported only to boxy, maproot -> boxy-backup,
# mode 750); falls back to /var/backups/boxy on the SD card if the NAS is unreachable.
# Keeps the newest $KEEP archives at the destination.
set -eu
umask 027                                   # archives readable by owner/group only
NAS="${BOXY_BACKUP_NAS:-192.168.42.61:/mnt/main/backups/boxy}"
MNT=/mnt/boxy-nas
LOCAL=/var/backups/boxy
KEEP=6
mounted=""

mkdir -p "$MNT"
if mountpoint -q "$MNT" || timeout 30 mount -t nfs -o rw,soft,timeo=100,retrans=2 "$NAS" "$MNT" 2>/dev/null; then
  DEST="$MNT"; mountpoint -q "$MNT" && mounted=1
else
  logger -t boxy-backup "NAS $NAS not reachable, using $LOCAL"
  DEST="$LOCAL"
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
  home/barbara/.kodi/userdata \
  etc/systemd/system/boxy-splash.service etc/systemd/system/boxy-backup.service \
  etc/systemd/system/boxy-backup.timer etc/systemd/system/boxy-netwatch.service \
  etc/systemd/system/boxy-netwatch.timer var/lib/kodi-siri-bridge \
  2>/dev/null || [ $? -eq 1 ]          # 1 = a file changed while reading: fine
mv "$out.tmp" "$out"

ls -1t "$DEST"/boxy-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
msg="backup: $out ($(du -h "$out" | cut -f1))"
echo "$msg"; logger -t boxy-backup "$msg"
sync
[ -n "$mounted" ] && umount "$MNT" || true
