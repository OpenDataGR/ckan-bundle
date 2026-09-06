(function (root) {
  'use strict';

  var DEFAULT_STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
  var DEFAULT_RASTER_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
  var DEFAULT_ATTRIBUTION = '&copy; OpenStreetMap contributors &copy; CARTO';
  var CARTO_URL = /^https?:\/\/(?:[^/?#]+\.)*cartocdn\.com(?::\d+)?(?:[/?#]|$)/i;

  function addApiKey(url, apiKey) {
    if (!url || !apiKey || !CARTO_URL.test(url) || /(?:[?&])key=/.test(url)) {
      return url;
    }

    var hashIndex = url.indexOf('#');
    var hash = hashIndex === -1 ? '' : url.slice(hashIndex);
    var base = hashIndex === -1 ? url : url.slice(0, hashIndex);
    var separator = base.indexOf('?') === -1 ? '?' : '&';
    return base + separator + 'key=' + encodeURIComponent(apiKey) + hash;
  }

  function transformRequest(apiKey, returnObject) {
    return function (url) {
      var transformed = addApiKey(url, apiKey);
      return returnObject ? {url: transformed} : transformed;
    };
  }

  function greekNameExpression() {
    return [
      'coalesce',
      ['get', 'name:el'],
      ['get', 'name'],
      ['get', 'name_en']
    ];
  }

  function isNameToken(value) {
    return value === '{name}' || value === '{name_en}' || value === '{name:el}';
  }

  function isNameField(value) {
    if (isNameToken(value)) {
      return true;
    }

    return !!(
      value &&
      Array.isArray(value.stops) &&
      value.stops.length &&
      value.stops.every(function (stop) {
        return Array.isArray(stop) && isNameToken(stop[1]);
      })
    );
  }

  function nonMaritimeFilter(filter) {
    var maritimeFilter = ['==', 'maritime', 0];
    var result;

    if (!Array.isArray(filter) || !filter.length) {
      return maritimeFilter;
    }

    if (filter[0] === 'all') {
      result = filter.filter(function (part, index) {
        return !(
          index > 0 &&
          Array.isArray(part) &&
          part.length > 1 &&
          part[1] === 'maritime'
        );
      });
      result.push(maritimeFilter);
      return result;
    }

    return ['all', filter, maritimeFilter];
  }

  function prepareStyle(style) {
    var prepared = JSON.parse(JSON.stringify(style));
    prepared.metadata = prepared.metadata || {};
    prepared.metadata['data-gov-gr:label-language'] = 'el,name,name_en';
    prepared.metadata['data-gov-gr:hide-maritime-boundaries'] = true;

    (prepared.layers || []).forEach(function (layer) {
      if (
        layer.type === 'symbol' &&
        layer.layout &&
        isNameField(layer.layout['text-field'])
      ) {
        layer.layout['text-field'] = greekNameExpression();
      }

      if (layer['source-layer'] === 'boundary') {
        layer.filter = nonMaritimeFilter(layer.filter);
      }
    });

    return prepared;
  }

  function isWebGLSupported() {
    var canvas;
    var context;

    if (
      root.maplibregl &&
      typeof root.maplibregl.supported === 'function'
    ) {
      return root.maplibregl.supported();
    }

    if (!root.document || typeof root.document.createElement !== 'function') {
      return false;
    }

    try {
      canvas = root.document.createElement('canvas');
      context = canvas.getContext('webgl2') || canvas.getContext('webgl');
      return !!(context && typeof context.getParameter === 'function');
    } catch (error) {
      return false;
    }
  }

  function whenLeafletVectorMapReady(vectorLayer, callback) {
    var callbackCalled = false;

    function notify() {
      var vectorMap;

      if (callbackCalled) {
        return;
      }

      vectorMap = vectorLayer.getMaplibreMap();
      if (!vectorMap) {
        return;
      }

      callbackCalled = true;
      callback(vectorMap);
    }

    vectorLayer.once('add', notify);
    notify();
    return notify;
  }

  function loadStyle(options) {
    options = options || {};
    var styleUrl = options.styleUrl || DEFAULT_STYLE_URL;
    var requestUrl = addApiKey(styleUrl, options.apiKey || '');

    if (!root.fetch) {
      return Promise.reject(new Error('Fetch API is not available'));
    }

    return root.fetch(requestUrl, {credentials: 'same-origin'}).then(function (response) {
      if (!response.ok) {
        throw new Error('Unable to load vector style (HTTP ' + response.status + ')');
      }
      return response.json();
    }).then(prepareStyle);
  }

  function addLeafletBasemap(map, options) {
    options = options || {};
    var apiKey = options.apiKey || '';
    var attribution = options.attribution || DEFAULT_ATTRIBUTION;
    var layerGroup = root.L.layerGroup();
    var vectorLayer;
    var fallbackLayer;
    var completed = false;
    var resolveReady;

    layerGroup.getAttribution = function () {
      return attribution;
    };

    layerGroup.cartoVectorReady = new Promise(function (resolve) {
      resolveReady = resolve;
    });

    function finish(mode) {
      if (!completed) {
        completed = true;
        resolveReady({mode: mode});
      }
    }

    function useFallback(reason) {
      if (fallbackLayer) {
        return fallbackLayer;
      }

      if (vectorLayer && layerGroup.hasLayer(vectorLayer)) {
        layerGroup.removeLayer(vectorLayer);
      }

      if (typeof options.fallbackFactory === 'function') {
        fallbackLayer = options.fallbackFactory();
      } else {
        fallbackLayer = root.L.tileLayer(
          addApiKey(options.fallbackUrl || DEFAULT_RASTER_URL, apiKey),
          {
            attribution: attribution,
            subdomains: options.subdomains || 'abcd',
            maxZoom: options.maxZoom || 20
          }
        );
      }

      layerGroup.addLayer(fallbackLayer);
      finish('raster');
      if (root.console && root.console.warn) {
        root.console.warn(
          'CARTO vector basemap unavailable; raster fallback enabled.',
          reason || ''
        );
      }
      return fallbackLayer;
    }

    if (!root.maplibregl) {
      useFallback(new Error('MapLibre GL is not loaded'));
      return layerGroup;
    }

    if (!isWebGLSupported()) {
      useFallback(new Error('WebGL is not supported by MapLibre GL'));
      return layerGroup;
    }

    if (!root.L.maplibreGL) {
      useFallback(new Error('Leaflet MapLibre adapter is not registered'));
      return layerGroup;
    }

    loadStyle({styleUrl: options.styleUrl, apiKey: apiKey}).then(function (style) {
      var loaded = false;
      vectorLayer = root.L.maplibreGL({
        style: style,
        attributionControl: false,
        transformRequest: transformRequest(apiKey, true)
      });
      var notifyVectorMapReady = whenLeafletVectorMapReady(vectorLayer, function (vectorMap) {
        vectorMap.once('load', function () {
          loaded = true;
          finish('vector');
        });
        vectorMap.on('error', function (event) {
          var status = event && event.error && event.error.status;
          if (!loaded || status === 401 || status === 403) {
            useFallback(event && event.error ? event.error : event);
          }
        });
        vectorMap.getCanvas().addEventListener('webglcontextlost', useFallback, {once: true});
      });
      layerGroup.addLayer(vectorLayer);
      notifyVectorMapReady();
    }).catch(useFallback);

    return layerGroup;
  }

  root.CkanCartoVector = {
    DEFAULT_STYLE_URL: DEFAULT_STYLE_URL,
    DEFAULT_RASTER_URL: DEFAULT_RASTER_URL,
    DEFAULT_ATTRIBUTION: DEFAULT_ATTRIBUTION,
    addApiKey: addApiKey,
    transformRequest: transformRequest,
    prepareStyle: prepareStyle,
    isWebGLSupported: isWebGLSupported,
    whenLeafletVectorMapReady: whenLeafletVectorMapReady,
    loadStyle: loadStyle,
    addLeafletBasemap: addLeafletBasemap
  };
})(this);
