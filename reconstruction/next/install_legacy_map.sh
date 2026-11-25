#!/usr/bin/env bash
# Reuse the exact MapLibre distribution installed by the previous BIMA2 dashboard.
set -euo pipefail
ROOT=/opt/BIMA2_NEXT/app
OLD=/opt/JAES_SIMULASI_BIMA2
PKG=$(find "$OLD" -type f -path '*/node_modules/maplibre-gl/dist/maplibre-gl.js' -print -quit)
if [[ -z "$PKG" ]];then echo 'Legacy MapLibre distribution not found; no files changed';exit 1;fi
DIST=$(dirname "$PKG")
test -s "$DIST/maplibre-gl.css"
python3 - "$DIST/../package.json" <<'PYCODE'
import json,sys
p=json.load(open(sys.argv[1]));assert p['name']=='maplibre-gl';print("Legacy MapLibre version:",p['version'])
PYCODE
mkdir -p "$ROOT/map-assets"
for f in maplibre-gl.js maplibre-gl.css;do
 install -m 0644 "$DIST/$f" "$ROOT/map-assets/$f.new"
 mv "$ROOT/map-assets/$f.new" "$ROOT/map-assets/$f"
done
sha256sum "$ROOT/map-assets/maplibre-gl.js" "$ROOT/map-assets/maplibre-gl.css"
echo "Legacy MapLibre assets installed from $DIST"
