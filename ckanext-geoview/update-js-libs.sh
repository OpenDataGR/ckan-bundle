#!/bin/bash -e

CURRENT_DIR="$(pwd)"
VENDOR_DIR="$CURRENT_DIR/ckanext/geoview/public/js/vendor"

declare -a libs=(
  "jszip;/node_modules/jszip/dist/jszip.min.js;/jszip/"
  "jszip-utils;/node_modules/jszip-utils/dist/jszip-utils.min.js;/jszip-utils/"
  "leaflet (js);/node_modules/leaflet/dist/leaflet.js;/leaflet/"
  "leaflet (css);/node_modules/leaflet/dist/leaflet.css;/leaflet/"
  "leaflet (images);/node_modules/leaflet/dist/images;/leaflet/"
  "leaflet_providers;/node_modules/leaflet-providers/leaflet-providers.js;/leaflet-providers/"
  "leaflet_spin;/node_modules/leaflet-spin/leaflet.spin.js;/leaflet-spin/"
  "openlayers;/node_modules/ol/dist/ol.js;/openlayers/"
  "openlayers (css);/node_modules/ol/ol.css;/openlayers/"
  "proj4leaflet;/node_modules/proj4leaflet/src/proj4leaflet.js;/proj4leaflet/"
  "proj4;/node_modules/proj4/dist/proj4.js;/proj4/"
  "spinjs;/node_modules/spin.js/spin.js;/spin.js/"
  "underscore;/node_modules/underscore/underscore-min.js;/underscore/" 
)

for lib in "${libs[@]}"
do
  IFS=";" read -r -a items <<< "${lib}"

  echo "Copying ${items[0]}..."
  DEST_DIR="${VENDOR_DIR}${items[2]}"
  mkdir -p "${DEST_DIR}"
  cp -r "${CURRENT_DIR}${items[1]}" "$DEST_DIR"
done

# Vector basemap dependencies are kept under versioned filenames so the CKAN
# webasset definitions and browser caches change explicitly on upgrades.
MAPLIBRE_VENDOR_DIR="$VENDOR_DIR/maplibre"
OLMS_VENDOR_DIR="$VENDOR_DIR/ol-mapbox-style"
MAPLIBRE_CSS_VENDOR_DIR="$CURRENT_DIR/ckanext/geoview/public/css/vendor/maplibre"

mkdir -p "$MAPLIBRE_VENDOR_DIR" "$OLMS_VENDOR_DIR" "$MAPLIBRE_CSS_VENDOR_DIR"
cp "$CURRENT_DIR/node_modules/maplibre-gl/dist/maplibre-gl.js" \
  "$MAPLIBRE_VENDOR_DIR/maplibre-gl-5.6.1.js"
patch --quiet \
  "$MAPLIBRE_VENDOR_DIR/maplibre-gl-5.6.1.js" \
  "$CURRENT_DIR/vendor-patches/maplibre-gl-ckan-requirejs.patch"
cp "$CURRENT_DIR/node_modules/maplibre-gl/dist/maplibre-gl.css" \
  "$MAPLIBRE_CSS_VENDOR_DIR/maplibre-gl-5.6.1.css"
cp "$CURRENT_DIR/node_modules/maplibre-gl/LICENSE.txt" \
  "$MAPLIBRE_VENDOR_DIR/MAPLIBRE-LICENSE.txt"
cp "$CURRENT_DIR/node_modules/@maplibre/maplibre-gl-leaflet/leaflet-maplibre-gl.js" \
  "$MAPLIBRE_VENDOR_DIR/leaflet-maplibre-gl-0.1.3.js"
patch --quiet \
  "$MAPLIBRE_VENDOR_DIR/leaflet-maplibre-gl-0.1.3.js" \
  "$CURRENT_DIR/vendor-patches/maplibre-gl-leaflet-ckan-requirejs.patch"
cp "$CURRENT_DIR/node_modules/@maplibre/maplibre-gl-leaflet/LICENSE" \
  "$MAPLIBRE_VENDOR_DIR/LEAFLET-ADAPTER-LICENSE.txt"
cp "$CURRENT_DIR/node_modules/ol-mapbox-style/dist/olms.js" \
  "$OLMS_VENDOR_DIR/olms-12.3.1.js"
cp "$CURRENT_DIR/node_modules/ol-mapbox-style/LICENSE" \
  "$OLMS_VENDOR_DIR/LICENSE.txt"
