const test = require('node:test');
const assert = require('node:assert/strict');

const featureHighlight = require(
    '../../ckanext/geoview/public/js/feature_highlight.js'
);

function createMap(hitProvider) {
    return {
        registeredHandler: null,
        hitOptions: null,
        on(eventName, handler) {
            assert.equal(eventName, 'pointermove');
            this.registeredHandler = handler;
        },
        forEachFeatureAtPixel(pixel, callback, options) {
            assert.deepEqual(pixel, [10, 20]);
            this.hitOptions = options;
            hitProvider(callback, options);
        }
    };
}

test('canSetFeatureStyle accepts only features with a callable setStyle', () => {
    assert.equal(featureHighlight.canSetFeatureStyle(null), false);
    assert.equal(featureHighlight.canSetFeatureStyle({}), false);
    assert.equal(featureHighlight.canSetFeatureStyle({setStyle: true}), false);
    assert.equal(
        featureHighlight.canSetFeatureStyle({setStyle() {}}),
        true
    );
});

test('pointer handler ignores vector-tile RenderFeature objects', () => {
    const overlayLayer = {kind: 'overlay'};
    const renderFeature = {kind: 'render-feature'};
    const map = createMap((callback) => {
        assert.equal(callback(renderFeature, overlayLayer), false);
    });
    const isOverlayLayer = (layer) => layer === overlayLayer;
    const handler = featureHighlight.install(
        map,
        {name: 'highlight'},
        isOverlayLayer
    );

    assert.equal(map.registeredHandler, handler);
    assert.doesNotThrow(() => handler({pixel: [10, 20]}));
    assert.doesNotThrow(() => handler({pixel: [10, 20]}));
    assert.equal(map.hitOptions.layerFilter, isOverlayLayer);
});

test('pointer handler highlights and then resets a styleable overlay feature', () => {
    const overlayLayer = {kind: 'overlay'};
    const highlightStyle = {name: 'highlight'};
    const appliedStyles = [];
    const feature = {
        setStyle(style) {
            appliedStyles.push(style);
        }
    };
    let returnFeature = true;
    const map = createMap((callback) => {
        if (returnFeature) {
            assert.equal(callback(feature, overlayLayer), true);
        }
    });
    const handler = featureHighlight.createPointerMoveHandler(
        map,
        highlightStyle,
        (layer) => layer === overlayLayer
    );

    handler({pixel: [10, 20]});
    returnFeature = false;
    handler({pixel: [10, 20]});

    assert.deepEqual(appliedStyles, [highlightStyle, undefined]);
});

test('pointer handler ignores styleable features outside overlay layers', () => {
    const basemapLayer = {kind: 'basemap'};
    let setStyleCalls = 0;
    const feature = {
        setStyle() {
            setStyleCalls += 1;
        }
    };
    const map = createMap((callback) => {
        assert.equal(callback(feature, basemapLayer), false);
    });
    const handler = featureHighlight.createPointerMoveHandler(
        map,
        {name: 'highlight'},
        () => false
    );

    handler({pixel: [10, 20]});

    assert.equal(setStyleCalls, 0);
});
