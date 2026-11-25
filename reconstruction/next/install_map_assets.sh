#!/usr/bin/env bash
set -euo pipefail
cd /opt/BIMA2_NEXT/app
mkdir -p map-assets
for name in leaflet.js leaflet.css; do
 case "$name" in
 leaflet.js) expected='20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';;
 leaflet.css) expected='p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';;
 esac
 curl -fsSL --retry 2 "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/$name" -o "map-assets/$name.new"
 actual=$(openssl dgst -sha256 -binary "map-assets/$name.new" | openssl base64 -A)
 test "$actual" = "$expected"
 mv "map-assets/$name.new" "map-assets/$name"
 chmod 644 "map-assets/$name"
done
