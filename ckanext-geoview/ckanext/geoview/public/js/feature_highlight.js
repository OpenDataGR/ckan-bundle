/* global self */

(function(root, factory) {
    var api = factory();

    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.CKAN_GEOVIEW_FEATURE_HIGHLIGHT = api;
    }
}(typeof self !== 'undefined' ? self : this, function() {
    function canSetFeatureStyle(feature) {
        return !!(feature && typeof feature.setStyle === 'function');
    }

    function createPointerMoveHandler(map, highlightStyle, isOverlayLayer) {
        var selected = null;

        return function(event) {
            if (canSetFeatureStyle(selected)) {
                selected.setStyle(undefined);
            }
            selected = null;

            map.forEachFeatureAtPixel(event.pixel, function(feature, layer) {
                if (!isOverlayLayer(layer) || !canSetFeatureStyle(feature)) {
                    return false;
                }

                selected = feature;
                feature.setStyle(highlightStyle);
                return true;
            }, {
                layerFilter: isOverlayLayer
            });
        };
    }

    function install(map, highlightStyle, isOverlayLayer) {
        var handler = createPointerMoveHandler(
            map,
            highlightStyle,
            isOverlayLayer
        );
        map.on('pointermove', handler);
        return handler;
    }

    return {
        canSetFeatureStyle: canSetFeatureStyle,
        createPointerMoveHandler: createPointerMoveHandler,
        install: install
    };
}));
