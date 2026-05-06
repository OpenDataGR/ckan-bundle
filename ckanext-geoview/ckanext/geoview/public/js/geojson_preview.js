// geojson preview module
ckan.module('geojsonpreview', function (jQuery, _) {
  return {
    options: {
      table: '<div class="table-container"><table class="table table-striped table-bordered table-condensed"><tbody>{body}</tbody></table></div>',
      row:'<tr><th>{key}</th><td>{value}</td></tr>',
      style: {
        opacity: 0.7,
        fillOpacity: 0.1,
        weight: 2
      },
      i18n: {
        'error': _('An error occurred: %(text)s %(error)s'),
        'file_too_big': _('This GeoJSON file is too big to be previewed. Please download it locally.')
      }
    },
    initialize: function () {
      var self = this;

      self.el.empty();

      if (this.options.max_file_size !== 'None' && preload_resource.size &&
        preload_resource.size > this.options.max_file_size) {
        var msg = this.i18n('file_too_big');
        self.el.append($("<div class='data-viewer-error'><p class='text-danger'>" + msg + "</p></div>"));
        return
      }



      self.el.append($("<div></div>").attr("id","map"));
      self.map = ckan.commonLeafletMap('map', this.options.map_config, {attributionControl: false});

      // hack to make leaflet use a particular location to look for images
      L.Icon.Default.imagePath = this.options.site_url + 'js/vendor/leaflet/images/';

      // GeoServer may return Greek Grid GeoJSON using either a short EPSG code
      // or OGC URN/URL CRS names. Register all common aliases for proj4leaflet.
      var epsg2100 = '+proj=tmerc +lat_0=0 +lon_0=24 +k=0.9996 ' +
        '+x_0=500000 +y_0=0 +ellps=GRS80 ' +
        '+towgs84=-199.87,74.79,246.62,0,0,0,0 +units=m +no_defs +type=crs';
      proj4.defs('EPSG:2100', epsg2100);
      proj4.defs('urn:ogc:def:crs:EPSG::2100', epsg2100);
      proj4.defs('http://www.opengis.net/gml/srs/epsg.xml#2100', epsg2100);

      // The standard CRS for GeoJSON according to RFC 7946 is
      // urn:ogc:def:crs:OGC::CRS84, but proj4s uses a different name
      // for it. See https://github.com/ckan/ckanext-geoview/issues/51
      proj4.defs['OGC:CRS84'] = proj4.defs['EPSG:4326'];
      
      // Use proxy_url if available (from template_variables), otherwise use original URL
      var resourceUrl = (preload_resource['proxy_url']) ? preload_resource['proxy_url'] : preload_resource['url'];
      
      jQuery.getJSON(resourceUrl).done(
        function(data){
          self.showPreview(data);
        })
      .fail(
        function(jqXHR, textStatus, errorThrown) {
          self.showError(jqXHR, textStatus, errorThrown);
        }
      );
    },

    showError: function (jqXHR, textStatus, errorThrown) {
      if (textStatus == 'error' && jqXHR.responseText.length) {
        this.el.html(jqXHR.responseText);
      } else {
        this.el.html(this.i18n('error', {text: textStatus, error: errorThrown}));
      }
    },

    showPreview: function (geojsonFeature) {
      var self = this;
      var gjLayer = L.Proj.geoJson(geojsonFeature, {
        style: self.options.style,
        onEachFeature: function(feature, layer) {
          var body = '';
          if (feature.properties) {
            jQuery.each(feature.properties, function(key, value){
              if (value != null && typeof value === 'object') {
                value = JSON.stringify(value);
              }
              body += L.Util.template(self.options.row, {key: key, value: value});
            });
            var popupContent = L.Util.template(self.options.table, {body: body});
            layer.bindPopup(popupContent);
          }
        }
      }).addTo(self.map);
      self.map.fitBounds(gjLayer.getBounds());
    }
  };
});
