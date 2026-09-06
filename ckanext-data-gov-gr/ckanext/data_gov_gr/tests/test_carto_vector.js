'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const publicDirectory = path.resolve(__dirname, '..', 'public');
const fallbackWarnings = [];
const sandbox = {
  Promise: Promise,
  console: {
    warn: function () {
      fallbackWarnings.push(Array.from(arguments));
    }
  }
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(publicDirectory, 'carto_vector.js'), 'utf8'),
  sandbox
);

const helper = sandbox.CkanCartoVector;
assert(helper, 'CkanCartoVector must be exported');

const adapterSandbox = {
  L: {
    Layer: {
      extend: function () {
        return function MaplibreGLLayer() {};
      }
    }
  },
  maplibregl: {}
};
let amdFactoryRegistered = false;
adapterSandbox.define = function () {
  amdFactoryRegistered = true;
};
adapterSandbox.define.amd = {};
vm.createContext(adapterSandbox);
vm.runInContext(
  fs.readFileSync(
    path.join(publicDirectory, 'vendor', 'maplibre', 'leaflet-maplibre-gl-0.1.3.js'),
    'utf8'
  ),
  adapterSandbox
);
assert.strictEqual(
  amdFactoryRegistered,
  false,
  'The adapter must prefer Leaflet browser globals over CKAN RequireJS'
);
assert.strictEqual(typeof adapterSandbox.L.maplibreGL, 'function');

const maplibreSource = fs.readFileSync(
  path.join(publicDirectory, 'vendor', 'maplibre', 'maplibre-gl-5.6.1.js'),
  'utf8'
);
assert(
  maplibreSource.indexOf("typeof window !== 'undefined'") <
    maplibreSource.indexOf("typeof define === 'function' && define.amd"),
  'The MapLibre bundle must prefer browser globals over AMD'
);

assert.strictEqual(
  helper.addApiKey('https://tiles.basemaps.cartocdn.com/vector/tiles.json', 'a b'),
  'https://tiles.basemaps.cartocdn.com/vector/tiles.json?key=a%20b'
);
assert.strictEqual(
  helper.addApiKey('https://tiles.basemaps.cartocdn.com/vector/tiles.json?key=first', 'second'),
  'https://tiles.basemaps.cartocdn.com/vector/tiles.json?key=first'
);
assert.strictEqual(
  helper.addApiKey('https://example.com/vector/tiles.json', 'secret'),
  'https://example.com/vector/tiles.json'
);
assert.strictEqual(
  helper.addApiKey('https://evilcartocdn.com/vector/tiles.json', 'secret'),
  'https://evilcartocdn.com/vector/tiles.json'
);

const prepared = helper.prepareStyle({
  version: 8,
  layers: [
    {type: 'symbol', layout: {'text-field': '{name_en}'}},
    {
      type: 'line',
      'source-layer': 'boundary',
      filter: ['all', ['==', 'admin_level', 2], ['==', 'maritime', 1]]
    }
  ]
});

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(prepared.layers[0].layout['text-field'])),
  ['coalesce', ['get', 'name:el'], ['get', 'name'], ['get', 'name_en']]
);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(prepared.layers[1].filter)),
  ['all', ['==', 'admin_level', 2], ['==', 'maritime', 0]]
);

const style = JSON.parse(
  fs.readFileSync(
    path.join(publicDirectory, 'basemaps', 'carto-positron-el-no-maritime.json'),
    'utf8'
  )
);
const boundaryLayers = style.layers.filter(
  (layer) => layer['source-layer'] === 'boundary'
);
assert(boundaryLayers.length > 0, 'The style must contain boundary layers');
boundaryLayers.forEach((layer) => {
  assert(
    JSON.stringify(layer.filter).includes('["==","maritime",0]'),
    `${layer.id} must exclude maritime boundaries`
  );
});

sandbox.L = {
  layerGroup: function () {
    const layers = [];
    return {
      _layers: layers,
      addLayer: function (layer) { layers.push(layer); return this; },
      hasLayer: function (layer) { return layers.includes(layer); },
      removeLayer: function (layer) {
        const index = layers.indexOf(layer);
        if (index !== -1) layers.splice(index, 1);
        return this;
      }
    };
  },
  tileLayer: function (url, options) {
    return {url: url, options: options};
  }
};
sandbox.maplibregl = {};
sandbox.document = {
  createElement: function (tagName) {
    assert.strictEqual(tagName, 'canvas');
    return {
      getContext: function (contextName) {
        if (contextName === 'webgl2') {
          return {getParameter: function () {}};
        }
        return null;
      }
    };
  }
};
assert.strictEqual(
  helper.isWebGLSupported(),
  true,
  'MapLibre 5.x without supported() must use a real canvas WebGL probe'
);

let leafletAddHandler;
let readyCallbackCount = 0;
const delayedVectorLayer = {
  vectorMap: undefined,
  once: function (eventName, callback) {
    assert.strictEqual(eventName, 'add');
    leafletAddHandler = callback;
  },
  getMaplibreMap: function () {
    return this.vectorMap;
  }
};
const notifyVectorMapReady = helper.whenLeafletVectorMapReady(
  delayedVectorLayer,
  function (vectorMap) {
    readyCallbackCount += 1;
    assert.strictEqual(vectorMap.id, 'delayed-maplibre-map');
  }
);
assert.strictEqual(readyCallbackCount, 0);
delayedVectorLayer.vectorMap = {id: 'delayed-maplibre-map'};
leafletAddHandler();
notifyVectorMapReady();
assert.strictEqual(
  readyCallbackCount,
  1,
  'A delayed GeoJSON Leaflet layer must initialize MapLibre exactly once'
);

sandbox.maplibregl = {supported: function () { return false; }};
const fallbackGroup = helper.addLeafletBasemap({}, {
  apiKey: 'fallback key',
  fallbackUrl: 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'
});
assert.strictEqual(fallbackGroup._layers.length, 1);
assert.strictEqual(
  fallbackGroup._layers[0].url,
  'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png?key=fallback%20key'
);
assert.strictEqual(fallbackWarnings.length, 1);
assert.strictEqual(
  fallbackWarnings[0][1].message,
  'WebGL is not supported by MapLibre GL'
);

console.log('CARTO vector helper and style tests passed');
