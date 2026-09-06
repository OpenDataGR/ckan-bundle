document.addEventListener('DOMContentLoaded', function () {
  console.log('Initializing map search...');

  // Έλεγγος αν υπάρχει ο χάρτης στη σελίδα
  const mapElement = document.getElementById('map');
  if (!mapElement) {
    console.error('Map element not found!');
    return;
  }

  // Έλεγχος για ενεργό χωρικό φίλτρο
  checkAndUpdateSpatialFilterUI();

  // Αρχικοποίηση χάρτη
  const savedCenter = localStorage.getItem('map_center');
  const savedZoom = localStorage.getItem('map_zoom');

  let map;

  function markMapTilesAsDecorative() {
    const tiles = mapElement.querySelectorAll('.leaflet-tile');
    tiles.forEach((tile) => {
      tile.setAttribute('alt', '');
      tile.setAttribute('role', 'presentation');
      tile.setAttribute('aria-hidden', 'true');
    });

    const vectorCanvas = mapElement.querySelector('.maplibregl-canvas');
    if (vectorCanvas) {
      vectorCanvas.setAttribute('role', 'presentation');
      vectorCanvas.setAttribute('aria-hidden', 'true');
      vectorCanvas.setAttribute('tabindex', '-1');
    }
  }

  function refreshMapSize() {
    if (!map) {
      return;
    }

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        map.invalidateSize();
        markMapTilesAsDecorative();
      });
    });
  }

  try {
    if (savedCenter && savedZoom) {
      const centerCoords = savedCenter.split(',').map(parseFloat);
      const zoomLevel = parseInt(savedZoom, 10);
      map = L.map('map').setView(centerCoords, zoomLevel);
    } else {
      map = L.map('map').setView([38.0, 23.7], 6);
    }

    // Επιλογή basemap από server-side config (εκτεθειμένο στο DOM)
    const basemapKey = (mapElement.dataset.basemap || 'carto_light_all').trim();
    const cartoApiKey = (mapElement.dataset.cartoApiKey || '').trim();
    const vectorStyleUrl = (mapElement.dataset.vectorStyleUrl || '/basemaps/carto-positron-el-no-maritime.json').trim();
    const vectorFallbackBasemap = (mapElement.dataset.vectorFallbackBasemap || 'carto_light_all').trim();

    function cartoTileUrl(url) {
      if (!cartoApiKey) {
        return url;
      }

      const separator = url.includes('?') ? '&' : '?';
      return `${url}${separator}key=${encodeURIComponent(cartoApiKey)}`;
    }

    function rasterBasemapByKey(key) {
      switch (key) {
        case 'osm':
          return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
          });

        case 'carto_light_nolabels':
          return L.tileLayer(cartoTileUrl('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png'), {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
          });

        case 'carto_voyager_nolabels':
          return L.tileLayer(cartoTileUrl('https://{s}.basemaps.cartocdn.com/rastertiles/voyager_nolabels/{z}/{x}/{y}{r}.png'), {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
          });

        case 'esri_light_gray':
          return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri'
          });

        case 'eox_osm':
          return L.tileLayer('https://tiles.maps.eox.at/wmts/1.0.0/osm_3857/default/g/{z}/{y}/{x}.jpg', {
            attribution: '<a href="https://maps.eox.at">EOX::Maps</a> | Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, Rendering &copy; <a href="https://eox.at">EOX</a> and <a href="https://github.com/mapserver/basemaps">MapServer</a>'
          });

        case 'carto_light_all':
        default:
          return L.tileLayer(cartoTileUrl('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'), {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
          });
      }
    }

    function addBasemapByKey(key) {
      if (key === 'carto_vector') {
        const safeFallbackKey = vectorFallbackBasemap === 'carto_vector'
          ? 'carto_light_all'
          : vectorFallbackBasemap;

        if (window.CkanCartoVector) {
          return window.CkanCartoVector.addLeafletBasemap(map, {
            styleUrl: vectorStyleUrl,
            apiKey: cartoApiKey,
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            fallbackFactory: function () {
              return rasterBasemapByKey(safeFallbackKey);
            }
          }).addTo(map);
        }

        return rasterBasemapByKey(safeFallbackKey).addTo(map);
      }

      return rasterBasemapByKey(key).addTo(map);
    }

    addBasemapByKey(basemapKey);
    markMapTilesAsDecorative();
    refreshMapSize();

    console.log('Map initialized successfully');

    // Συνάρτηση ενημέρωσης bbox
    function updateBBoxInput() {
      const bounds = map.getBounds();
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      const extBBoxValue = `${sw.lng.toFixed(6)},${sw.lat.toFixed(6)},${ne.lng.toFixed(6)},${ne.lat.toFixed(6)}`;
      document.getElementById('ext_bbox_input').value = extBBoxValue;
    }

    map.on('moveend', updateBBoxInput);
    map.on('layeradd', markMapTilesAsDecorative);
    map.on('load', markMapTilesAsDecorative);
    map.on('zoomend', markMapTilesAsDecorative);
    map.on('moveend', markMapTilesAsDecorative);
    updateBBoxInput();

    // Χειρισμός κουμπιού αναζήτησης
    const searchBtn = document.getElementById('map-search-button');
    if (searchBtn) {
      searchBtn.addEventListener('click', function (e) {
        e.preventDefault();
        updateBBoxInput();

        // Αποθήκευση κατάστασης χάρτη
        const center = map.getCenter();
        const zoom = map.getZoom();
        localStorage.setItem('map_center', `${center.lat},${center.lng}`);
        localStorage.setItem('map_zoom', zoom);

        // Υποβολή φόρμας
        const form = document.getElementById('dataset-search-form');
        if (form) {
          let extInput = form.querySelector('input[name="ext_bbox"]');
          if (!extInput) {
            extInput = document.createElement('input');
            extInput.type = 'hidden';
            extInput.name = 'ext_bbox';
            form.appendChild(extInput);
          }
          extInput.value = document.getElementById('ext_bbox_input').value;
          if (window.dataGovGrPrepareSearchSort) {
            // Το native form.submit() δεν ενεργοποιεί submit event, οπότε
            // εφαρμόζουμε χειροκίνητα τη λογική που αφαιρεί το default sort.
            window.dataGovGrPrepareSearchSort(form);
          }
          form.submit();
        }
      });
    }

    const filtersModalObserver = new MutationObserver(() => {
      if (document.body.classList.contains('filters-modal')) {
        refreshMapSize();
      }
    });
    filtersModalObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

    window.addEventListener('resize', refreshMapSize);

  } catch (error) {
    console.error('Error initializing map:', error);
  }

  // Συναρτήσεις για το κουμπί απόκρυψης
  function checkAndUpdateSpatialFilterUI() {
      const urlParams = new URLSearchParams(window.location.search);
      const currentExtBbox = urlParams.get('ext_bbox');
      const hasActiveSpatialFilter = currentExtBbox && currentExtBbox.trim() !== '';

      if (hasActiveSpatialFilter) {
          showSpatialFilterClearButton();
      } else {
        hideSpatialFilterClearButton();
      }
  }

  function showSpatialFilterClearButton() {
      const textContainer = document.querySelector('.map-search-text-container');
      if (textContainer) {
          textContainer.classList.add('active-spatial-filter');

          let clearButton = textContainer.querySelector('.spatial-filter-close');
          if (!clearButton) {
              clearButton = document.createElement('a');
              clearButton.className = 'spatial-filter-close';
              clearButton.href = removeSpatialFilterUrl();
              clearButton.innerHTML = '<i class="fa fa-solid fa-circle-xmark"></i>';
              clearButton.title = 'Κατάργηση χωρικού φίλτρου';
              textContainer.appendChild(clearButton);
          } else {
              clearButton.style.display = 'block';
              clearButton.href = removeSpatialFilterUrl();
          }
      }
  }

  function hideSpatialFilterClearButton() {
      const textContainer = document.querySelector('.map-search-text-container');
      if (textContainer) {
        textContainer.classList.remove('active-spatial-filter');
      }

      const clearButtons = document.querySelectorAll('.spatial-filter-close');
      clearButtons.forEach(btn => {
          btn.style.display = 'none';
      });
  }

  function removeSpatialFilterUrl() {
    const url = new URL(window.location);
    url.searchParams.delete('ext_bbox');
    return url.toString();
  }

  // Listener για αλλαγές URL
  window.addEventListener('popstate', checkAndUpdateSpatialFilterUI);
});
