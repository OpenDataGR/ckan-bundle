ckan.module("matomo", function(jQuery, _) {
  "use strict";

  function hasPaq() {
    return (typeof window !== "undefined" &&
      window._paq &&
      typeof window._paq.push === "function");
  }

  function toNumber(value) {
    if (value === null || value === undefined) return null;
    var n = Number(value);
    return isFinite(n) ? n : null;
  }

  function trackEvent(category, action, name, value) {
    if (!hasPaq()) return;
    if (!category || !action) return;

    var payload = ["trackEvent", String(category), String(action)];
    var numericValue = toNumber(value);
    if (name) {
      payload.push(String(name));
    } else if (numericValue !== null) {
      // Αν υπάρχει value αλλά δεν υπάρχει name/href, στέλνουμε κενό name ώστε
      // το value να μην “μετακινηθεί” στη θέση του name στο Matomo.
      payload.push("");
    }
    if (numericValue !== null) payload.push(numericValue);
    window._paq.push(payload);
  }

  return {
     initialize: function() {
      jQuery("a.resource-url-analytics").on("click", function() {

        let resource_url = encodeURIComponent(jQuery(this).prop("href"));
        if (resource_url) {
          trackEvent("Resource", "Open", resource_url);
        }
      });

      // Γενική καταγραφή κλικ μέσω data attributes:
      // data-matomo-category, data-matomo-action, data-matomo-name (προαιρετικό), data-matomo-value (προαιρετικό)
      jQuery(document).on("click", "[data-matomo-category][data-matomo-action]", function() {
        var $el = jQuery(this);
        var category = $el.attr("data-matomo-category");
        var action = $el.attr("data-matomo-action");
        var name = $el.attr("data-matomo-name") || $el.prop("href") || "";
        var value = $el.attr("data-matomo-value");
        trackEvent(category, action, name, value);
      });
    }
  };
});
