/**
 * Συμπλήρωση/συγχρονισμός του πεδίου «Δικαιώματα» (rights) με το label της
 * επιλεγμένης άδειας (license) για πόρους.
 *
 * Απαιτήσεις:
 * - Σε νέες εγγραφές, να προσυμπληρώνεται (π.χ. "Creative Commons Attribution 4.0 International (CC BY 4.0)").
 * - Να παρακολουθεί τις αλλαγές του license και να ενημερώνει δυναμικά.
 * - Να μη «πατάει» χειροκίνητη επεξεργασία του rights από τον χρήστη.
 */

(function () {
  var RIGHTS_PREFIX = "Τα δεδομένα διατίθενται κάτω από την άδεια : ";

  function getEl(id) {
    return document.getElementById(id);
  }

  function getDatasetIdFromPathname() {
    var p = (window.location && window.location.pathname) || "";
    // Πιθανά μοτίβα:
    // - /dataset/<id>/resource/new
    // - /dataset/<id>/resource/<rid>/edit
    // - /package/<id>/resource/new
    // - /package/<id>/resource/<rid>/edit
    var m = p.match(/\/(?:dataset|package)\/([^\/?#]+)/i);
    return m && m[1] ? decodeURIComponent(m[1]) : "";
  }

  function normalizeText(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function getSelectedOptionLabel(selectEl) {
    if (!selectEl || !selectEl.options || selectEl.selectedIndex < 0) {
      return "";
    }
    var opt = selectEl.options[selectEl.selectedIndex];
    return normalizeText(opt && opt.text);
  }

  function buildRightsText(licenseLabel) {
    var label = normalizeText(licenseLabel);
    if (!label) {
      return "";
    }
    return RIGHTS_PREFIX + label;
  }

  function setRightsValue(rightsEl, label) {
    rightsEl.value = buildRightsText(label);
  }

  function init() {
    // Τα IDs προκύπτουν από τα scheming snippets:
    // - license: searchable_select -> id="field-license"
    // - rights: markdown -> id="field-rights"
    var licenseEl = getEl("field-license");
    var rightsEl = getEl("field-rights");

    if (!licenseEl || !rightsEl) {
      return;
    }

    var datasetId = getDatasetIdFromPathname();
    var datasetLicenseTitlePromise = null;

    // Ο χρήστης μπορεί να επεξεργαστεί το πεδίο «Δικαιώματα» πάντα.
    // Όταν αλλάζει το license, ξαναγεμίζουμε με το default λεκτικό μας.

    function getDatasetLicenseTitle() {
      if (!datasetId) {
        return Promise.resolve("");
      }
      if (datasetLicenseTitlePromise) {
        return datasetLicenseTitlePromise;
      }
      datasetLicenseTitlePromise = fetch(
        "/api/3/action/package_show?id=" + encodeURIComponent(datasetId),
        { credentials: "same-origin" }
      )
        .then(function (r) {
          return r.json();
        })
        .then(function (payload) {
          if (!payload || payload.success !== true || !payload.result) {
            return "";
          }
          return normalizeText(payload.result.license_title || "");
        })
        .catch(function () {
          return "";
        });
      return datasetLicenseTitlePromise;
    }

    function syncFromLicense(force) {
      var currentRights = normalizeText(rightsEl.value);
      var label = getSelectedOptionLabel(licenseEl);

      // 1) Αν υπάρχει άδεια στον πόρο, χρησιμοποιούμε το label της.
      if (label) {
        if (force || !currentRights) {
          setRightsValue(rightsEl, label);
        }
        return;
      }

      // 2) Αν η άδεια στον πόρο είναι κενή (κληρονομείται),
      //    fallback στον τίτλο άδειας του dataset.
      if (force || !currentRights) {
        getDatasetLicenseTitle().then(function (datasetTitle) {
          if (!datasetTitle) {
            // Αν αλλάξει η άδεια και δεν βρεθεί dataset license, καθαρίζουμε.
            if (force) {
              rightsEl.value = "";
            }
            return;
          }
          setRightsValue(rightsEl, datasetTitle);
        });
      }
    }

    // Αρχικό auto-fill (μόνο όταν είναι κενό).
    syncFromLicense(false);

    // Δυναμική ενημέρωση όταν αλλάζει η άδεια.
    function onLicenseChanged() {
      syncFromLicense(true);
    }

    // Native event
    licenseEl.addEventListener("change", onLicenseChanged);

    // Select2 (CKAN autocomplete module) events - για περισσότερη αξιοπιστία
    if (window.jQuery) {
      try {
        window.jQuery(licenseEl).on("change", onLicenseChanged);
        window.jQuery(licenseEl).on("select2-selecting select2:select", onLicenseChanged);
      } catch (e) {
        // ignore
      }
    }
  }

  // Το script φορτώνεται δυναμικά μετά το DOMContentLoaded (βλ. base.html),
  // άρα δεν πρέπει να βασιζόμαστε μόνο σε αυτό το event.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
