#!/usr/bin/env bash
set -euo pipefail
OLD=/opt/JAES_SIMULASI_BIMA2
TARGET="$OLD/web/ferry-dashboard"
for u in bima2-dashboard bima2-api bima2-state bima2-history bima2-cctv-watch bima2-yolo-hls; do
 if systemctl is-active --quiet "$u.service"; then echo "Still active: $u"; exit 1; fi
done
for u in bima2-next.service bima2-ais.service bima2-ais-gdrive.timer; do systemctl is-active --quiet "$u"; done
# Check running units and process references before deleting only the known obsolete frontend.
if [[ -d "$TARGET" && ! -L "$TARGET" && "$(realpath "$TARGET")" == "$TARGET" ]]; then
 for u in $(systemctl list-units --type=service --state=running --no-legend --plain | awk '{print $1}'); do
  if systemctl show "$u" -p ExecStart -p WorkingDirectory -p EnvironmentFiles | grep -Fq "$TARGET"; then echo "Active dependency: $u"; exit 1; fi
 done
 for p in /proc/[0-9]*/cwd /proc/[0-9]*/exe; do
  link=$(readlink "$p" || true); if [[ "$link" == "$TARGET" || "$link" == "$TARGET/"* ]]; then echo "Active process: $p"; exit 1; fi
 done
 test -s /opt/BIMA2_NEXT/app/map-assets/maplibre-gl.js
 test -s /opt/BIMA2_NEXT/app/map-assets/maplibre-gl.css
 du -sh "$TARGET"
 rm -rf -- "$TARGET"
 echo "Removed obsolete frontend $TARGET"
fi
# Other legacy Python files share the AIS runtime; inventory, do not guess.
find "$OLD" -maxdepth 2 -type d -not -path '*/.venv/*' -print
systemctl is-active bima2-ais.service bima2-ais-gdrive.timer bima2-next.service
