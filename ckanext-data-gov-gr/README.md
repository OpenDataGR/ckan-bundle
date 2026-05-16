[![Tests](https://github.com//ckanext-data-gov-gr/workflows/Tests/badge.svg?branch=main)](https://github.com//ckanext-data-gov-gr/actions)

# ckanext-data-gov-gr

**TODO:** Put a description of your extension here:  What does it do? What features does it have? Consider including some screenshots or embedding a video!


## Requirements

**TODO:** For example, you might want to mention here which versions of CKAN this
extension works with.

If your extension works across different versions you can add the following table:

Compatibility with core CKAN versions:

| CKAN version    | Compatible?   |
| --------------- | ------------- |
| 2.6 and earlier | not tested    |
| 2.7             | not tested    |
| 2.8             | not tested    |
| 2.9             | not tested    |

Suggested values:

* "yes"
* "not tested" - I can't think of a reason why it wouldn't work
* "not yet" - there is an intention to get it working
* "no"


## Installation

**TODO:** Add any additional install steps to the list below.
   For example installing any non-Python dependencies or adding any required
   config settings.

To install ckanext-data-gov-gr:

1. Activate your CKAN virtual environment, for example:

     . /usr/lib/ckan/default/bin/activate

2. Clone the source and install it on the virtualenv

    git clone https://github.com//ckanext-data-gov-gr.git
    cd ckanext-data-gov-gr
    pip install -e .
	pip install -r requirements.txt

3. Add `data-gov-gr` to the `ckan.plugins` setting in your CKAN
   config file (by default the config file is located at
   `/etc/ckan/default/ckan.ini`).

4. Restart CKAN. For example if you've deployed CKAN with Apache on Ubuntu:

     sudo service apache2 reload


## Config settings

Optional settings:

    # Hide the "Data and Resources" section on data-service ("API") dataset pages.
    # (optional, default: yes)
    ckanext.data_gov_gr.data_service.hide_resources_section = yes

    # Αρχική σελίδα: custom URL για το κουμπί «Προβολή Στατιστικών» στην ενότητα
    # «Στατιστικά Επανάχρησης Δεδομένων».
    # Αν είναι κενό, χρησιμοποιείται η τρέχουσα συμπεριφορά:
    # route stats.index αν είναι διαθέσιμο, αλλιώς fallback στο /stats.
    # (προαιρετικό, default: κενό)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Αρχική.
    ckanext.data_gov_gr.home.reuse_stats.view_all_url =

    # Ευρετήριο οργανισμών: εμφάνιση επιλογών ταξινόμησης βάσει επισκεψιμότητας.
    # Όταν είναι yes και υπάρχουν διαθέσιμα CKAN tracking δεδομένα, στο dropdown
    # ταξινόμησης εμφανίζονται οι επιλογές «Περισσότερες επισκέψεις» και
    # «Λιγότερες επισκέψεις».
    # (προαιρετικό, default: no)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Οργανισμοί.
    ckanext.data_gov_gr.organization_index.visits_sort.enabled = no

    # Ευρετήριο οργανισμών: προεπιλεγμένη ταξινόμηση βάσει επισκεψιμότητας.
    # Όταν είναι yes, το ευρετήριο οργανισμών ταξινομείται εξ ορισμού με
    # «Περισσότερες επισκέψεις». Ισχύει μόνο αν είναι ενεργό και το
    # ckanext.data_gov_gr.organization_index.visits_sort.enabled.
    # Αν δεν υπάρχουν tracking δεδομένα, χρησιμοποιείται fallback σε
    # ταξινόμηση βάσει πλήθους datasets.
    # (προαιρετικό, default: no)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Οργανισμοί.
    ckanext.data_gov_gr.organization_index.visits_sort.default = no

    # Footer: σελίδα δήλωσης προσβασιμότητας.
    # Δηλώστε μόνο το slug και όχι πλήρες URL ή /pages path.
    # Παράδειγμα: αν η σελίδα είναι /pages/accessibility, η τιμή είναι accessibility.
    # (προαιρετικό, default: κενό)
    # Αν λείπει ή είναι κενό, το link "Προσβασιμότητα" δεν εμφανίζεται στο footer.
    ckanext.data_gov_gr.pages.accessibility_statement = accessibility

    # Εμφάνιση/απόκρυψη του ενημερωτικού κειμένου για την άδεια μεταδεδομένων
    # στο κάτω μέρος της φόρμας δημιουργίας/επεξεργασίας dataset.
    # (προαιρετικό, default: no)
    # Αν λείπει από το ckan.ini, το κείμενο δεν εμφανίζεται.
    ckanext.data_gov_gr.dataset.show_metadata_license_disclaimer = no

    # HVD: προεπιλεγμένη εφαρμοστέα νομοθεσία που προστίθεται αυτόματα στο
    # applicable_legislation όταν επιλεγεί μία ή περισσότερες HVD κατηγορίες
    # σε dataset ή data-service. Η ίδια τιμή χρησιμοποιείται και ως fallback
    # για τον σύνδεσμο "εδώ" στο ενημερωτικό κείμενο του πεδίου hvd_category.
    # (προαιρετικό, default: http://data.europa.eu/eli/reg_impl/2023/138/oj)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config.
    ckanext.data_gov_gr.hvd.applicable_legislation.default = http://data.europa.eu/eli/reg_impl/2023/138/oj

    # HVD: ξεχωριστό URL για τον σύνδεσμο "εδώ" στο ενημερωτικό κείμενο του
    # πεδίου hvd_category. Αν είναι κενό, χρησιμοποιείται η τιμή του
    # ckanext.data_gov_gr.hvd.applicable_legislation.default.
    # (προαιρετικό, default: κενό)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config.
    ckanext.data_gov_gr.hvd.category_notice.url =

    # Μετάβαση στη φόρμα προσθήκης πόρου μετά τη δημιουργία νέου dataset από το UI.
    # Όταν είναι yes, το dataset αποθηκεύεται κανονικά ως active και ο χρήστης
    # μεταφέρεται στο /dataset/<name>/resource/new. Η προσθήκη πόρου παραμένει
    # προαιρετική και η ρύθμιση εφαρμόζεται μόνο στον τύπο package "dataset".
    # (προαιρετικό, default: no)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Διάφορα.
    ckanext.data_gov_gr.dataset.redirect_to_resource_after_create = no

    # Απόκρυψη του tab "Επαναχρήσεις" από το dashboard του χρήστη.
    # (προαιρετικό, default: no)
    # Αν λείπει από το ckan.ini ή είναι no, το tab εμφανίζεται κανονικά.
    # Αν είναι yes, το tab κρύβεται από το navigation του dashboard.
    ckanext.data_gov_gr.user.hide_showcase_tab = no

    # Header: preset λογότυπο data.gov.gr.
    # Επιλέγει ποια εικόνα από τον φάκελο /images/data-gov-gr/ εμφανίζεται στο header
    # όταν το ckan.site_logo είναι άδειο (δεν έχει ανέβει custom logo).
    # Διαθέσιμες τιμές (filenames):
    #   white-gradient-blue-trimmed-transparent.png  ← default
    #   data.gov.gr-cyan-trimmed-transparent.png
    #   data.gov.gr-gray-trimmed-transparent.png
    #   data.gov.gr-orange-trimmed-transparent.png
    #   data.gov.gr-turquoise-trimmed-transparent.png
    #   data.gov.gr-white-trimmed-transparent.png
    # (προαιρετικό, default: white-gradient-blue-trimmed-transparent.png)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → «Preset λογότυπο header».
    # Προτεραιότητα: ckan.site_logo (uploaded/URL) > logo_preset > site_title κείμενο.
    ckanext.data_gov_gr.header.logo_preset = white-gradient-blue-trimmed-transparent.png

    # Header: λογότυπο Γραμματείας Διακυβέρνησης Δεδομένων AI.
    # Αν είναι yes, εμφανίζεται το λογότυπο της Γραμματείας δεξιά του λογοτύπου data.gov.gr
    # στο header, με λευκή κάθετη γραμμή ως διαχωριστικό.
    # (προαιρετικό, default: no)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Header.
    ckanext.data_gov_gr.header.secretariat_logo.enabled = no

    # Εμφάνιση λογοτύπου gov.gr στο footer (κάτω αριστερά, πριν το λογότυπο Υπ. Ψηφιακής Διακυβέρνησης).
    # (προαιρετικό, default: yes)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Footer.
    ckanext.data_gov_gr.footer.government_logo.enabled = yes

    # Εμφάνιση λογοτύπου Greece 2.0 NextGenerationEU στο footer (μετά τα υπάρχοντα λογότυπα).
    # (προαιρετικό, default: yes)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά → Footer.
    ckanext.data_gov_gr.footer.greece_2_nextgeneration_logo.enabled = yes

    # Παραλλαγή λογοτύπου Υπ. Ψηφιακής Διακυβέρνησης στο footer (κάτω αριστερά).
    # Τιμές: light (ανοιχτή απόχρωση μπλε) ή dark (σκοτεινή απόχρωση μπλε).
    # (προαιρετικό, default: light)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    ckanext.data_gov_gr.footer.mindigital_logo_variant = light

    # Σελίδα επικοινωνίας / υποστήριξης
    # ------------------------------------

    # Βασικό URL των οδηγών (GitBook).
    # Χρησιμοποιείται ως βάση για τα links οδηγών και το iframe embed στη σελίδα επικοινωνίας.
    # (προαιρετικό, default: https://data-gov-gr.gitbook.io/guides)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    guides_base_url = https://data-gov-gr.gitbook.io/guides

    # Εμφάνιση/απόκρυψη του iframe με τους οδηγούς (GitBook) στη σελίδα επικοινωνίας.
    # Ανεξάρτητο από το guides_base_url — επιτρέπει να έχεις ορισμένο URL για τα links
    # αλλά να αποκρύψεις το embedded iframe.
    # (προαιρετικό, default: true)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    ckanext.contact.guides_embed.enabled = true

    # Εμφάνιση/απόκρυψη της ενότητας «Συχνές Ερωτήσεις» (FAQ GitBook embed) στη σελίδα επικοινωνίας.
    # (προαιρετικό, default: false)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    ckanext.contact.support_faq.enabled = false

    # GitBook PDF export — Space ID και API token.
    # Απαιτούνται και τα δύο για να εμφανιστεί το κουμπί «Λήψη PDF» στη σελίδα /more.
    # (προαιρετικό, default: κενό)
    ckanext.data_gov_gr.gitbook.space_id = <GitBook Space ID>
    ckanext.data_gov_gr.gitbook.api_token = <GitBook API Token>

    # Μέγιστος αριθμός σελίδων που φορτώνονται στο GitBook PDF.
    # Προστίθεται ως παράμετρος limit στο URL του GitBook, ώστε να
    # περιλαμβάνονται όλες οι σελίδες και όχι μόνο οι πρώτες.
    # (προαιρετικό, default: 1000)
    ckanext.data_gov_gr.gitbook.pdf_page_limit = 1000

    # Αυτόματο άνοιγμα print dialog κατά τη λήψη PDF οδηγών.
    # Όταν είναι false (default), το κουμπί «Λήψη PDF» ανοίγει σε νέα καρτέλα
    # τη σελίδα PDF του GitBook (με limit παράμετρο), και ο χρήστης εκτυπώνει χειροκίνητα.
    # Όταν είναι true, ο server κατεβάζει τη σελίδα, ενσωματώνει auto-print JavaScript,
    # και ανοίγει αυτόματα το print dialog του browser μετά από 2 δευτερόλεπτα.
    # (προαιρετικό, default: false)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    ckanext.data_gov_gr.gitbook.pdf_auto_print = false

    # Χρόνος αποθήκευσης (TTL) σε δευτερόλεπτα για τη Redis cache της λίστας
    # σελίδων GitBook που εμφανίζεται στο dropdown «Λήψη οδηγού ανά ενότητα».
    # (προαιρετικό, default: 86400 — 1 ημέρα)
    ckanext.data_gov_gr.gitbook.pages_cache_ttl = 86400

    # Αυτόματο άνοιγμα print dialog κατά τη λήψη PDF μεμονωμένης ενότητας.
    # Ανεξάρτητο από το pdf_auto_print που αφορά τη λήψη όλων των οδηγών.
    # (προαιρετικό, default: false)
    ckanext.data_gov_gr.gitbook.pdf_per_page_auto_print = true

    # Καθυστέρηση (σε milliseconds) πριν ανοίξει το print dialog κατά τη λήψη
    # PDF μεμονωμένης ενότητας. Ισχύει μόνο όταν pdf_per_page_auto_print = true.
    # 0 = άμεσο άνοιγμα print dialog χωρίς καθυστέρηση.
    # (προαιρετικό, default: 0)
    ckanext.data_gov_gr.gitbook.pdf_per_page_print_delay_ms = 0

    # Εμφάνιση/απόκρυψη του πλαισίου «Κατεβάστε τους οδηγούς (PDF)» (όλοι οι οδηγοί)
    # στη σελίδα Εργαλείων (/more).
    # (προαιρετικό, default: true)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    ckanext.data_gov_gr.gitbook.pdf_all_guides_panel.enabled = true

    # Εμφάνιση/απόκρυψη του πλαισίου «Λήψη οδηγού ανά ενότητα» (dropdown)
    # στη σελίδα Εργαλείων (/more).
    # (προαιρετικό, default: true)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Οδηγοί (GitBook).
    ckanext.data_gov_gr.gitbook.pdf_per_page_panel.enabled = true

    # Footer: σελίδα Συχνών Ερωτήσεων (FAQ).
    # Δηλώστε μόνο το slug της CKAN σελίδας (ckanext-pages) και όχι πλήρες URL ή /pages path.
    # Παράδειγμα: αν η σελίδα είναι /pages/faq, η τιμή είναι faq.
    # (προαιρετικό, default: κενό)
    # Αν λείπει ή είναι κενό, το link «Συχνές Ερωτήσεις» δεν εμφανίζεται στο footer.
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    ckanext.data_gov_gr.pages.faq = faq

    # Footer: σελίδα Πολιτικής Cookies.
    # Δηλώστε μόνο το slug της CKAN σελίδας (ckanext-pages) και όχι πλήρες URL ή /pages path.
    # Παράδειγμα: αν η σελίδα είναι /pages/cookies-policy, η τιμή είναι cookies-policy.
    # (προαιρετικό, default: κενό)
    # Αν λείπει ή είναι κενό, το link «Πολιτική Cookies» δεν εμφανίζεται στο footer.
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    ckanext.data_gov_gr.pages.cookies_policy = cookies-policy

    # Footer: σελίδα Πολιτικής Απορρήτου.
    # Δηλώστε μόνο το slug της CKAN σελίδας (ckanext-pages) και όχι πλήρες URL ή /pages path.
    # Παράδειγμα: αν η σελίδα είναι /pages/privacy-policy, η τιμή είναι privacy-policy.
    # (προαιρετικό, default: κενό)
    # Αν λείπει ή είναι κενό, το link «Πολιτική Απορρήτου» δεν εμφανίζεται στο footer.
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    ckanext.data_gov_gr.pages.privacy_policy = privacy-policy

    # Σελίδα αναζήτησης συνόλων δεδομένων — σύνδεσμος τεκμηρίωσης API.
    # Πλήρες URL που εμφανίζεται ως «API Docs» στο κάτω μέρος της σελίδας αναζήτησης,
    # αντικαθιστώντας τον default σύνδεσμο προς docs.ckan.org. Ανοίγει σε νέα καρτέλα.
    # Παράλληλα, το λεκτικό «API» εμφανίζεται ως απλό κείμενο (όχι link).
    # (προαιρετικό, default: κενό — χρησιμοποιείται ο default σύνδεσμος του CKAN)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    ckanext.data_gov_gr.search.api_doc_url = https://...

    # Matomo — Cookie / Tracking Consent
    # ------------------------------------

    # Λειτουργία συγκατάθεσης cookies/tracking για το Matomo.
    # Ελέγχει αν εμφανίζεται banner συγκατάθεσης και πώς αλληλεπιδρά με το Matomo tracking.
    #
    # Τιμές:
    #   disabled          — Χωρίς banner, τρέχουσα συμπεριφορά (default).
    #   tracking_consent  — Πλήρης συγκατάθεση: κανένα tracking (requests + cookies)
    #                       μέχρι ο χρήστης να αποδεχτεί. Αυστηρότερη GDPR συμμόρφωση.
    #   cookie_consent    — Συγκατάθεση μόνο για cookies: ανώνυμο tracking γίνεται
    #                       κανονικά, αλλά cookies (visitor identification) μόνο μετά
    #                       αποδοχή. Μέτρια GDPR συμμόρφωση.
    #   opt_out           — Tracking by default. Ο χρήστης μπορεί να εξαιρεθεί
    #                       μέσω του banner. Λιγότερο αυστηρό — μπορεί να μην αρκεί
    #                       για GDPR.
    #
    # (προαιρετικό, default: disabled)
    # Μπορεί επίσης να αλλάξει από το /ckan-admin/config → Γενικά.
    # Απαιτεί ενεργοποιημένο ckanext-matomo plugin.
    #
    # Σύνδεσμος Πολιτικής Cookies στο banner:
    # Αν έχει οριστεί η ρύθμιση ckanext.data_gov_gr.pages.cookies_policy (βλ. παραπάνω),
    # στο banner εμφανίζεται αυτόματα σύνδεσμος «Πολιτική Cookies» που οδηγεί στη
    # σελίδα /pages/<slug>. Αν η ρύθμιση είναι κενή, ο σύνδεσμος δεν εμφανίζεται.
    ckanext.matomo.consent_mode = disabled

## CSW harvester source config

Οι παρακάτω επιλογές δηλώνονται στο JSON config του CSW harvest source
(`ckanext-spatial` / `csw` harvester), όχι στο `ckan.ini`.

Παράδειγμα:

```json
{
  "default_tags": ["gis", "piraeus", "INSPIRE", "γεωχωρικά"],
  "default_extras": {
    "harvest_publisher": "piraeus",
    "dataset_name_prefix_from_file_identifier": "gis-piraeus-",
    "harvest_spatial_harvester": "csw"
  },
  "override_extras": false,
  "clean_tags": true,
  "validator_profiles": ["iso19139eden", "iso19139ngdc"],
  "typenames": "gmd:MD_Metadata",
  "layer_resource_base_url": "https://gis.piraeus.gov.gr/geoserver/wms#",
  "landing_page_base_url_from_file_identifier": "https://gis.piraeus.gov.gr/geonetwork/srv/eng/catalog.search#/metadata/",
  "default_dataset_fields": {
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"],
    "publisher": [{
      "uri": "https://example.org/org",
      "name": "Υπουργείο Διοικητικής Ανασυγκρότησης",
      "email": "info@example.org",
      "url": "https://example.org",
      "type": "http://purl.org/adms/publishertype/Company",
      "identifier": "org-identifier-001"
    }]
  },
  "override_default_dataset_fields": false,
  "default_resource_fields": {
    "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
  },
  "override_default_resource_fields": false,
  "resource_access_url_from_url": true,
  "resource_description_from_name": true,
  "resource_mimetype_from_distribution_format": true,
  "resource_rights_from_use_constraints": true,
  "resource_rights_plain_text_from_use_constraints": true,
  "wms_preview_from_online_resource": true,
  "wms_preview_from_wms_online_resources": false,
  "wms_preview_base_url": "https://gis.piraeus.gov.gr/geoserver/wms#",
  "wms_capabilities_url": "https://gis.piraeus.gov.gr/geoserver/wms?service=WMS&request=GetCapabilities&version=1.3.0",
  "wfs_capabilities_url": "https://gis.piraeus.gov.gr/geoserver/wfs?service=WFS&request=GetCapabilities&version=2.0.0",
  "preserve_resource_ids_by_url": true,
  "skip_data_service_records": false,
  "skip_dataset_when_no_non_uuid_layer_identifier": false,
  "skip_dataset_when_title_matches_layer_name": false,
  "safe_resource_format_inference": true,
  "outputschema": "gmd"
}
```

### CSW source URL

Στο harvest source URL προτιμάμε το καθαρό CSW endpoint χωρίς trailing slash.
Σε GeoNode/MapStore εγκαταστάσεις έχει παρατηρηθεί ότι το endpoint με trailing
slash μπορεί να αγνοεί τα CSW query parameters και να επιστρέφει HTML σελίδα
αντί για XML capabilities. Αυτό οδηγεί σε σφάλμα τύπου:

```text
Error contacting the CSW server: Opening and ending tag mismatch: link ... and head
```

Σωστό:

```text
https://gis.nikaia-rentis.gov.gr/catalogue/csw
```

Λάθος:

```text
https://gis.nikaia-rentis.gov.gr/catalogue/csw/
```

Γρήγορος έλεγχος:

```bash
curl -I "https://gis.nikaia-rentis.gov.gr/catalogue/csw?service=CSW&version=2.0.2&request=GetCapabilities"
```

Το response πρέπει να έχει `content-type: application/xml`, όχι `text/html`.

### `layer_resource_base_url`

Προαιρετικό. Όταν οριστεί, το extension προσθέτει ως πρώτο resource ένα WMS
resource για το αντίστοιχο layer του ISO record.

Το layer name διαβάζεται από τα dataset identifiers:

```xpath
//gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:identifier/gmd:RS_Identifier/gmd:code/gco:CharacterString
```

Από τις τιμές που επιστρέφονται αγνοούνται όσα μοιάζουν με UUID και
χρησιμοποιείται το πρώτο non-UUID value ως local layer name. Το τελικό URL είναι:

```text
layer_resource_base_url + layer_name
```

Το resource δημιουργείται με:

```json
{
  "format": "WMS",
  "name_translated": {
    "el": "<layer_name>",
    "en": "<layer_name>"
  },
  "description_translated": {
    "el": "Προεπισκόπηση συνόλου δεδομένων - <layer_name>",
    "en": "Προεπισκόπηση συνόλου δεδομένων - <layer_name>"
  }
}
```

Αν υπάρχει ήδη resource με το ίδιο URL, δεν δημιουργείται δεύτερο. Το υπάρχον
resource ενημερώνεται και μετακινείται πρώτο.

### `wms_capabilities_url` / `wfs_capabilities_url`

Προαιρετικά strings. Όταν οριστούν, το extension προσθέτει WMS και WFS
`GetCapabilities` resources αμέσως μετά το κύριο WMS preview resource του
dataset.

Παράδειγμα config:

```json
{
  "layer_resource_base_url": "https://gis.piraeus.gov.gr/geoserver/wms#",
  "wms_capabilities_url": "https://gis.piraeus.gov.gr/geoserver/wms?service=WMS&request=GetCapabilities&version=1.3.0",
  "wfs_capabilities_url": "https://gis.piraeus.gov.gr/geoserver/wfs?service=WFS&request=GetCapabilities&version=2.0.0"
}
```

Με layer `geonode:roads_DNR`, η σειρά πόρων γίνεται:

1. WMS preview resource από `layer_resource_base_url + layer_name`,
2. WMS capabilities resource με `format: XML` και
   `resource_locator_protocol: OGC:WMS`,
3. WFS capabilities resource με `format: XML` και
   `resource_locator_protocol: OGC:WFS`,
4. οι υπόλοιποι πόροι του ISO record.

Αν υπάρχει ήδη resource με το ίδιο capabilities URL, δεν δημιουργείται δεύτερο.
Το υπάρχον resource ενημερώνεται και μετακινείται στη σωστή θέση.

### `skip_dataset_when_no_non_uuid_layer_identifier`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true` και έχει οριστεί `layer_resource_base_url`, το extension
παραλείπει την εισαγωγή CSW records των οποίων τα dataset identifiers δεν
περιέχουν κανένα πραγματικό non-UUID layer name. Ο κανόνας στοχεύει περιπτώσεις
όπου το `layer_resource_base_url` θα κατέληγε να φτιάξει WMS preview URL με
metadata identifier αντί για layer name, π.χ.:

```text
https://gis.crete.gov.gr/geoserver/wms#m7614f0c-828c-459b-9534-e8be0d870cb5
```

Παράδειγμα config:

```json
{
  "layer_resource_base_url": "https://gis.crete.gov.gr/geoserver/wms#",
  "skip_dataset_when_no_non_uuid_layer_identifier": true
}
```

Αν υπάρχει έστω ένα non-UUID identifier, όπως `geonode:roads_DNR`, το dataset
δεν παραλείπεται.

### `skip_data_service_records`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension παραλείπει την εισαγωγή CSW records που το
`ckanext-spatial` έχει αναγνωρίσει ως CKAN packages τύπου `data-service`.

Η αναγνώριση γίνεται πριν κληθεί το hook του extension, από το ISO metadata,
όπως `gmd:hierarchyLevel` με τιμή `service` ή
`srv:SV_ServiceIdentification/srv:serviceType`.

Παράδειγμα config:

```json
{
  "skip_data_service_records": true
}
```

Χρήσιμο όταν μια CSW πηγή περιέχει και datasets και INSPIRE service records,
αλλά θέλουμε να καταχωρούνται μόνο τα datasets.

### `skip_dataset_when_title_matches_layer_name`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true` και έχει οριστεί `layer_resource_base_url`, το extension
παραλείπει την εισαγωγή CSW records των οποίων ο τίτλος δεν είναι περιγραφικός
αλλά είναι ίδιος με το layer name που διαβάζεται από τα dataset identifiers.

Η σύγκριση γίνεται με:

- το πλήρες layer name, π.χ. `geonode:roads_DNR`,
- το local layer name χωρίς workspace, π.χ. `roads_DNR`.

Τα `_` και `-` αντιμετωπίζονται ως ισοδύναμα separators, ώστε π.χ. layer
`rym_pireaus:rym_ras_010490FS000349_1932E` να ταιριάζει με τίτλο
`rym_ras_010490FS000349-1932E`.

Παράδειγμα config:

```json
{
  "layer_resource_base_url": "https://gis.crete.gov.gr/geoserver/wms#",
  "skip_dataset_when_title_matches_layer_name": true
}
```

Παράδειγμα που παραλείπεται:

```text
identifier: geonode:roads_DNR
title: roads_DNR
```

Παράδειγμα που δεν παραλείπεται:

```text
identifier: geonode:roads_DNR
title: Οδικό δίκτυο
```

### `wms_preview_from_online_resource`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension δημιουργεί πρώτο WMS preview resource από το
πρώτο ISO online resource που έχει protocol `OGC:WMS`.

Το layer name διαβάζεται από το `gmd:name` του ίδιου online resource:

```xml
<gmd:onLine>
  <gmd:CI_OnlineResource>
    <gmd:linkage>
      <gmd:URL>https://gis.nikaia-rentis.gov.gr/geoserver/ows</gmd:URL>
    </gmd:linkage>
    <gmd:protocol>
      <gco:CharacterString>OGC:WMS</gco:CharacterString>
    </gmd:protocol>
    <gmd:name>
      <gco:CharacterString>geonode:roads_DNR</gco:CharacterString>
    </gmd:name>
  </gmd:CI_OnlineResource>
</gmd:onLine>
```

Το τελικό preview URL παράγεται από:

```text
wms_preview_base_url + layer_name
```

Παράδειγμα config:

```json
{
  "wms_preview_from_online_resource": true,
  "wms_preview_base_url": "https://gis.nikaia-rentis.gov.gr/geoserver/wms#"
}
```

Το παραπάνω παράγει:

```text
https://gis.nikaia-rentis.gov.gr/geoserver/wms#geonode:roads_DNR
```

Αν υπάρχουν πολλά `OGC:WMS` online resources, χρησιμοποιείται μόνο το πρώτο.
Αν υπάρχει ήδη resource με το ίδιο τελικό URL, δεν δημιουργείται δεύτερο. Το
υπάρχον resource ενημερώνεται και μετακινείται πρώτο.

### `wms_preview_from_wms_online_resources`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension δημιουργεί WMS preview resources από όλα τα ISO
online resources των οποίων το protocol ξεκινάει με `OGC:WMS`.

Χρήσιμο για metadata όπου το protocol δεν είναι ακριβώς `OGC:WMS`, αλλά έχει
μορφή όπως:

```text
OGC:WMS-1.3.0-http-get-map
```

Το layer name διαβάζεται από το `gmd:name` του online resource και το τελικό URL
παράγεται από:

```text
wms_preview_base_url + layer_name
```

Παράδειγμα config:

```json
{
  "wms_preview_from_wms_online_resources": true,
  "wms_preview_base_url": "http://geoportal.ypen.gr/geoserver/wms#"
}
```

Με online resources:

```xml
<gmd:protocol>
  <gco:CharacterString>OGC:WMS-1.3.0-http-get-map</gco:CharacterString>
</gmd:protocol>
<gmd:name>
  <gco:CharacterString>AM.AirQualityManagementZone</gco:CharacterString>
</gmd:name>
```

παράγεται:

```text
http://geoportal.ypen.gr/geoserver/wms#AM.AirQualityManagementZone
```

Αν υπάρχουν πολλά WMS online resources, δημιουργείται ένας preview πόρος ανά
διακριτό `gmd:name`, με τη σειρά που εμφανίζονται στο XML. Αν υπάρχει ήδη
resource με το ίδιο τελικό URL, ενημερώνεται και μετακινείται στις πρώτες
θέσεις.

### `preserve_resource_ids_by_url`

Προαιρετικό boolean. Default: `true`.

Όταν είναι `true` ή λείπει από το config, το extension προσπαθεί να διατηρήσει
τα υπάρχοντα CKAN resource ids στο re-harvest, αντιστοιχίζοντας τους νέους πόρους
με τους παλιούς βάσει URL.

Αν ο πόρος έχει `resource_locator_protocol`, το protocol χρησιμοποιείται μαζί με
το URL, ώστε GeoNode πόροι WMS/WFS που μοιράζονται το ίδιο `/geoserver/ows` URL να
διατηρούν διαφορετικά ids.

Αν παλιότερο resource δεν έχει διαθέσιμο `resource_locator_protocol`, αλλά έχει
`format`, γίνεται δεύτερη προσπάθεια αντιστοίχισης με URL και format.

Αυτό βοηθά να παραμένουν συνδεδεμένα τα υπάρχοντα resource views, επειδή στο CKAN
τα views συνδέονται με το `resource_id`.

Για απενεργοποίηση:

```json
{
  "preserve_resource_ids_by_url": false
}
```

Ο κανόνας:

- δεν αλλάζει resource που έχει ήδη `id`,
- αγνοεί παλιά resources με state `deleted`,
- δεν αναθέτει το ίδιο παλιό `id` σε δύο νέους πόρους με ίδιο URL,
- δεν κάνει fallback σε σκέτο URL όταν υπάρχουν πολλαπλά παλιά resources με το
  ίδιο URL και δεν υπάρχει `resource_locator_protocol` για ασφαλή αντιστοίχιση.

### `dataset_name_prefix_from_file_identifier`

Προαιρετικό. Όταν οριστεί, το CKAN dataset `name` παράγεται από το prefix και το
ISO `fileIdentifier`.

Το `fileIdentifier` διαβάζεται από:

```xpath
//gmd:fileIdentifier/gco:CharacterString
```

Παράδειγμα:

```json
{
  "dataset_name_prefix_from_file_identifier": "gis-piraeus-"
}
```

με:

```xml
<gmd:fileIdentifier>
  <gco:CharacterString>dbc81cc1c-c3be-11f0-8de9-0242ac120002</gco:CharacterString>
</gmd:fileIdentifier>
```

παράγει:

```text
gis-piraeus-dbc81cc1c-c3be-11f0-8de9-0242ac120002
```

Η τιμή μπορεί να δηλωθεί είτε top-level στο harvest source config είτε μέσα στο
`default_extras`, ώστε να υποστηρίζονται υπάρχοντα CSW configs:

```json
{
  "default_extras": {
    "dataset_name_prefix_from_file_identifier": "gis-piraeus-"
  }
}
```

Αν η επιλογή λείπει ή είναι κενή, το dataset `name` δεν αλλάζει από αυτόν τον
κανόνα.

### `landing_page_base_url_from_file_identifier`

Προαιρετικό. Όταν οριστεί, το CKAN dataset `landing_page` παράγεται από το base
URL και το ISO `fileIdentifier`.

Το `fileIdentifier` διαβάζεται από:

```xpath
//gmd:fileIdentifier/gco:CharacterString
```

Παράδειγμα:

```json
{
  "landing_page_base_url_from_file_identifier": "https://gis.piraeus.gov.gr/geonetwork/srv/eng/catalog.search#/metadata/"
}
```

με:

```xml
<gmd:fileIdentifier>
  <gco:CharacterString>dbc81cc1c-c3be-11f0-8de9-0242ac120002</gco:CharacterString>
</gmd:fileIdentifier>
```

παράγει:

```text
https://gis.piraeus.gov.gr/geonetwork/srv/eng/catalog.search#/metadata/dbc81cc1c-c3be-11f0-8de9-0242ac120002
```

Αν η επιλογή λείπει ή είναι κενή, το `landing_page` δεν αλλάζει από αυτόν τον
κανόνα. Αν η επιλογή υπάρχει, το `landing_page` αντικαθίσταται με το παραγόμενο
URL.

### `default_dataset_fields`

Προαιρετικό. Επιτρέπει να δηλωθούν default τιμές για πεδία του CKAN dataset
(`package_dict`) από το JSON config του CSW harvest source.

Παράδειγμα για default HVD category σε όλα τα harvested datasets:

```json
{
  "default_dataset_fields": {
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"]
  }
}
```

Το παραπάνω καταχωρεί:

```python
package_dict["hvd_category"] = ["http://data.europa.eu/bna/c_ac64a52d"]
```

αν το `hvd_category` λείπει ή είναι κενό.

Η επιλογή είναι γενική και μπορεί να χρησιμοποιηθεί και για άλλα dataset fields,
με προσοχή στον τύπο τιμής που περιμένει το schema κάθε πεδίου.

Παράδειγμα για default publisher σε όλα τα harvested datasets:

```json
{
  "default_dataset_fields": {
    "publisher": [{
      "uri": "https://example.org/org",
      "name": "Υπουργείο Διοικητικής Ανασυγκρότησης",
      "email": "info@example.org",
      "url": "https://example.org",
      "type": "http://purl.org/adms/publishertype/Company",
      "identifier": "org-identifier-001"
    }]
  }
}
```

Το παραπάνω καταχωρεί το `package_dict["publisher"]`, αν λείπει ή είναι κενό.
Υποστηρίζονται όλα τα subfields του publisher schema, όπως `uri`, `name`,
`email`, `url`, `type` και `identifier`.

### `override_default_dataset_fields`

Προαιρετικό boolean. Default: `false`.

Ελέγχει αν οι τιμές του `default_dataset_fields` αντικαθιστούν υπάρχουσες τιμές
στο `package_dict`.

```json
{
  "default_dataset_fields": {
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"]
  },
  "override_default_dataset_fields": true
}
```

Όταν είναι `false` ή λείπει, υπάρχουσες μη κενές τιμές διατηρούνται. Όταν είναι
`true`, οι τιμές του config γράφονται στο dataset ακόμα και αν το πεδίο είχε ήδη
τιμή από το ISO ή από άλλο mapping.

### `default_resource_fields`

Προαιρετικό. Επιτρέπει να δηλωθούν default τιμές για πεδία κάθε CKAN resource από
το JSON config του CSW harvest source.

Παράδειγμα για default άδεια σε όλα τα harvested resources:

```json
{
  "default_resource_fields": {
    "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
  }
}
```

Το παραπάνω καταχωρεί:

```python
resource["license"] = "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
```

σε κάθε resource, αν το `license` λείπει ή είναι κενό.

Η επιλογή είναι γενική και μπορεί να χρησιμοποιηθεί και για άλλα resource fields,
με προσοχή στον τύπο τιμής που περιμένει το schema κάθε πεδίου.

### `override_default_resource_fields`

Προαιρετικό boolean. Default: `false`.

Ελέγχει αν οι τιμές του `default_resource_fields` αντικαθιστούν υπάρχουσες τιμές
στα resources.

```json
{
  "default_resource_fields": {
    "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
  },
  "override_default_resource_fields": true
}
```

Όταν είναι `false` ή λείπει, υπάρχουσες μη κενές τιμές διατηρούνται. Όταν είναι
`true`, οι τιμές του config γράφονται στα resources ακόμα και αν το πεδίο είχε
ήδη τιμή από το ISO ή από άλλο mapping.

### `resource_access_url_from_url`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension συμπληρώνει το `access_url` κάθε resource από το
ήδη καταχωρημένο `url`, μόνο αν το `access_url` λείπει ή είναι κενό.

```python
resource["access_url"] = resource["url"]
```

Αν το resource δεν έχει `url`, ο κανόνας δεν το αλλάζει.

### `resource_description_from_name`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension συμπληρώνει το `description_translated` κάθε
resource από το όνομά του, μόνο αν το `description_translated` λείπει ή είναι
κενό.

Αν υπάρχει δίγλωσσο `name_translated`, χρησιμοποιούνται οι αντίστοιχες τιμές:

```python
resource["description_translated"] = {
    "el": resource["name_translated"]["el"],
    "en": resource["name_translated"]["en"]
}
```

Αν δεν υπάρχει `name_translated`, χρησιμοποιείται το απλό `name` και για τις δύο
γλώσσες. Το απλό πεδίο `description` δεν αλλάζει από αυτόν τον κανόνα.

### `resource_rights_from_use_constraints`

Προαιρετικό boolean. Default: `true`.

Όταν είναι `true` ή λείπει από το config, το extension συμπληρώνει το `rights`
κάθε resource από ISO `useConstraints` με `otherRestrictions`, μόνο αν το
`rights` λείπει ή είναι κενό. Για απενεργοποίηση δηλώνεται ρητά:

```json
{
  "resource_rights_from_use_constraints": false
}
```

Ο κανόνας διαβάζει μόνο `useConstraints`:

```xpath
//gmd:resourceConstraints/gmd:MD_LegalConstraints[
  gmd:useConstraints/gmd:MD_RestrictionCode/@codeListValue='otherRestrictions'
]
```

Τα `accessConstraints` αγνοούνται από αυτόν τον κανόνα.

Πρώτα προτιμώνται INSPIRE `ConditionsApplyingToAccessAndUse` anchors. Για
παράδειγμα:

```xml
<gmd:resourceConstraints>
  <gmd:MD_LegalConstraints>
    <gmd:useConstraints>
      <gmd:MD_RestrictionCode codeListValue="otherRestrictions"/>
    </gmd:useConstraints>
    <gmd:otherConstraints>
      <gmx:Anchor xlink:href="http://inspire.ec.europa.eu/metadata-codelist/ConditionsApplyingToAccessAndUse/noConditionsApply">
        No conditions apply to access and use
      </gmx:Anchor>
    </gmd:otherConstraints>
  </gmd:MD_LegalConstraints>
</gmd:resourceConstraints>
```

καταχωρεί:

```python
resource["rights"] = (
    "http://inspire.ec.europa.eu/metadata-codelist/ConditionsApplyingToAccessAndUse/noConditionsApply"
    "\n\n"
    "No conditions apply to access and use"
)
```

Αν δεν βρεθεί τέτοιο INSPIRE URI, εφαρμόζεται by default fallback σε plain text
`otherConstraints`, π.χ. `gco:CharacterString` ή `LocalisedCharacterString`.
Αυτό καλύπτει ISO records που δηλώνουν τους όρους χρήσης ως απλό κείμενο:

```xml
<gmd:useConstraints>
  <gmd:MD_RestrictionCode codeListValue="otherRestrictions"/>
</gmd:useConstraints>
<gmd:otherConstraints>
  <gco:CharacterString>
    Η χρήση διέπεται από CC BY-SA 4.0
    (https://creativecommons.org/licenses/by-sa/4.0/deed.el).
  </gco:CharacterString>
</gmd:otherConstraints>
```

Σε αυτήν την περίπτωση το κείμενο μπαίνει στο `resource["rights"]`. Αν μέσα στο
κείμενο υπάρχει URL άδειας, συμπληρώνονται επίσης `license_url`,
`license_title`, και όπου είναι δυνατόν `license` με EU licence URI.

Το plain-text fallback απενεργοποιείται ανεξάρτητα από το βασικό rule:

```json
{
  "resource_rights_plain_text_from_use_constraints": false
}
```

### `resource_mimetype_from_distribution_format`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension διαβάζει IANA media type URI από το ISO
`distributionFormat` και το καταχωρεί στο `mimetype` όλων των resources του
dataset.

Το `mimetype` διαβάζεται από:

```xpath
//gmd:distributionInfo/gmd:MD_Distribution/gmd:distributionFormat/gmd:MD_Format/gmd:name/gco:CharacterString
```

Παράδειγμα:

```xml
<gmd:distributionInfo>
  <gmd:MD_Distribution>
    <gmd:distributionFormat>
      <gmd:MD_Format>
        <gmd:name>
          <gco:CharacterString>https://www.iana.org/assignments/media-types/image/tiff</gco:CharacterString>
        </gmd:name>
        <gmd:version gco:nilReason="inapplicable"/>
      </gmd:MD_Format>
    </gmd:distributionFormat>
  </gmd:MD_Distribution>
</gmd:distributionInfo>
```

Η τιμή εφαρμόζεται μόνο αν:

- ξεκινά με `https://www.iana.org/assignments/media-types/`,
- υπάρχει στο λεξιλόγιο `Media types` ως `tag["value_uri"]`.

Αν το resource έχει ήδη `mimetype`, η υπάρχουσα τιμή διατηρείται.

### `safe_resource_format_inference`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, το extension χρησιμοποιεί ασφαλέστερη λογική για να συμπληρώσει
το resource `format` από ISO online resources.

Σκοπός είναι να μην αντιμετωπίζονται ανθρώπινοι τίτλοι resource ως filenames.
Για παράδειγμα, χωρίς την ασφαλή λογική, ένα όνομα όπως:

```text
Υπηρεσίες Απεικόνισης (WMS) Δ. Κερατσινίου-Δραπετσώνας
```

μπορεί να θεωρηθεί λανθασμένα ότι έχει extension μετά την τελεία στο `Δ.` και να
δώσει λάθος `format`.

Με `safe_resource_format_inference: true`:

- γίνεται inference από `gmd:name` μόνο όταν μοιάζει με filename/path, π.χ.
  `dataset.geojson`;
- συνεχίζει να γίνεται inference από URL path, OGC query params και protocol,
- αν δεν προκύπτει αξιόπιστο format, το resource `format` δεν αλλάζει από αυτόν
  τον κανόνα.

Αν η επιλογή λείπει ή είναι `false`, παραμένει η παλαιότερη συμπεριφορά για λόγους
συμβατότητας.

## WMS capabilities harvester source config

Ο `wms_capabilities_harvester` δημιουργεί ένα CKAN dataset για κάθε named WMS
layer που υπάρχει σε WMS `GetCapabilities` document.

Ο harvester πρέπει να είναι ενεργός στο `ckan.plugins`:

```ini
ckan.plugins = ... harvest wms_capabilities_harvester ...
```

Αν ο harvester προστέθηκε πρόσφατα στα entry points, χρειάζεται editable install
και restart των CKAN / harvest worker processes:

```bash
cd /root/ckan/lib/default/src/ckanext-data-gov-gr
/usr/lib/ckan/default/bin/pip install -e .
```

### Τι παράγει ανά WMS layer

Για κάθε `<Layer>` με `<Name>` δημιουργείται ένα dataset με:

- `name` / harvest `guid`: από παραμετρικό prefix και normalized WMS layer name,
- `title_translated`: από το WMS `Title`,
- `notes_translated`: από το WMS `Abstract` ή fallback στο title,
- `tag_string`: από το WMS `KeywordList`, με δυνατότητα φιλτραρίσματος του layer
  name,
- `dcat_type`: `GEOSPATIAL`,
- `access_rights`: `PUBLIC`,
- `spatial_coverage`: `bbox` και `centroid` από `EX_GeographicBoundingBox`, με
  κενό `text`,
- resources για WMS preview, WMS capabilities και WFS capabilities.

Τα ελληνικά WMS metadata χρησιμοποιούνται και στα δύο language slots
(`el`, `en`) όταν δεν υπάρχει ξεχωριστή αγγλική τιμή στην πηγή.

### Παράδειγμα config

Οι παρακάτω επιλογές δηλώνονται στο JSON config του WMS harvest source, όχι στο
`ckan.ini`.

```json
{
  "dataset_name_prefix_from_layer_name": "gis-perifereia-kritis-selected-1-",
  "dataset_name_max_length": 100,
  "wms_preview_base_url": "https://gis.crete.gov.gr/geoserver/wms#",
  "wms_capabilities_url": "https://gis.crete.gov.gr/geoserver/wms?service=WMS&request=GetCapabilities&version=1.3.0",
  "wfs_capabilities_url": "https://gis.crete.gov.gr/geoserver/wfs?service=WFS&request=GetCapabilities&version=2.0.0",
  "default_dataset_fields": {
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"]
  },
  "default_resource_fields": {
    "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
  },
  "default_tags": ["gis", "crete", "INSPIRE", "γεωχωρικά"],
  "skip_dataset_when_title_matches_layer_name": true,
  "include_layer_name_keywords": false,
  "skip_keywords_matching": ["^v_[a-z0-9_]+$"],
  "gather_log_every": 100,
  "timeout": 60,
  "user_agent": "data.gov.gr CKAN WMS Harvester"
}
```

Για local δοκιμές μπορεί να δηλωθεί και local capabilities file:

```json
{
  "capabilities_file": "/root/geo/perifereia-kritis/capabilities/wms.xml"
}
```

Όταν υπάρχει `capabilities_file`, ο harvester διαβάζει αυτό το αρχείο αντί να
κατεβάσει το WMS capabilities URL.

### `dataset_name_prefix_from_layer_name`

Προαιρετικό string. Default: κενό.

Χρησιμοποιείται για να παραχθεί το CKAN dataset `name` και το harvest `guid`.
Το τελικό value είναι:

```text
normalize(dataset_name_prefix_from_layer_name + layer_name)
```

Παράδειγμα:

```json
{
  "dataset_name_prefix_from_layer_name": "gis-perifereia-kritis-selected-1-"
}
```

με WMS layer:

```text
gisvec:adm_poi_elstat_oikismos
```

παράγει:

```text
gis-perifereia-kritis-selected-1-gisvec-adm_poi_elstat_oikismos
```

Για συμβατότητα, αν λείπει το `dataset_name_prefix_from_layer_name`, ο harvester
κοιτάει και το παλιότερο key `dataset_name_prefix_from_file_identifier`.

### `dataset_name_max_length`

Προαιρετικός ακέραιος. Default: `100`, δηλαδή το μέγιστο μήκος που δέχεται το
CKAN για dataset `name`.

Αν το normalized `dataset_name_prefix_from_layer_name + layer_name` ξεπεράσει το
όριο, ο harvester το κόβει και προσθέτει σταθερό hash suffix. Έτσι το dataset
`name` παραμένει έγκυρο και deterministic για επόμενα re-harvests.

### `wms_preview_base_url`

Προαιρετικό string. Όταν οριστεί, δημιουργείται ο πρώτος resource του dataset ως
WMS preview resource:

```text
wms_preview_base_url + layer_name
```

Παράδειγμα:

```json
{
  "wms_preview_base_url": "https://gis.crete.gov.gr/geoserver/wms#"
}
```

με layer:

```text
gisvec:adm_poi_elstat_oikismos
```

παράγει resource URL:

```text
https://gis.crete.gov.gr/geoserver/wms#gisvec:adm_poi_elstat_oikismos
```

Ο resource έχει:

```json
{
  "format": "WMS",
  "resource_locator_protocol": "OGC:WMS",
  "access_url": "<ίδιο με το url>"
}
```

### `wms_capabilities_url`

Προαιρετικό string. Δηλώνει το WMS `GetCapabilities` URL.

Χρησιμοποιείται:

- ως URL από το οποίο κατεβαίνει το capabilities document, όταν δεν έχει δηλωθεί
  `capabilities_file`,
- ως δεύτερος resource σε κάθε dataset.

Αν λείπει, χρησιμοποιείται το harvest source URL.

Ο resource περιλαμβάνει το layer name στο `name_translated` και στο
`description_translated`, ώστε να μπορεί να εντοπιστεί εύκολα από τον χρήστη.

### `wfs_capabilities_url`

Προαιρετικό string. Όταν οριστεί, δημιουργείται τρίτος resource σε κάθε dataset
με το WFS `GetCapabilities` URL.

Ο resource έχει:

```json
{
  "format": "XML",
  "resource_locator_protocol": "OGC:WFS",
  "access_url": "<ίδιο με το url>"
}
```

Και εδώ το layer name μπαίνει στο `name_translated` και στο
`description_translated`.

### `capabilities_file`

Προαιρετικό string. Τοπικό path σε WMS capabilities XML αρχείο.

Χρήσιμο για δοκιμές χωρίς network ή για επαναλήψιμα harvest runs πάνω σε
συγκεκριμένο snapshot:

```json
{
  "capabilities_file": "/root/geo/perifereia-kritis/capabilities/wms.xml"
}
```

### `include_layer_name_keywords`

Προαιρετικό boolean. Default: `false`.

Το WMS `KeywordList` συχνά περιέχει ως keyword το ίδιο το layer name, είτε πλήρες
με workspace είτε ως local layer name:

```xml
<Name>agricultureypaat:agr_her_17_geo_armanogeia_1961_dia_3a_3</Name>
<KeywordList>
  <Keyword>agr_her_17_geo_armanogeia_1961_dia_3a_3</Keyword>
  <Keyword>WCS</Keyword>
  <Keyword>GeoTIFF</Keyword>
</KeywordList>
```

Με default συμπεριφορά (`false`) ο harvester αγνοεί keywords που είναι ίδια με:

- `agricultureypaat:agr_her_17_geo_armanogeia_1961_dia_3a_3`,
- `agr_her_17_geo_armanogeia_1961_dia_3a_3`.

Άρα καταχωρεί:

```text
WCS, GeoTIFF
```

Αν δηλωθεί:

```json
{
  "include_layer_name_keywords": true
}
```

τότε καταχωρείται και το local layer-name keyword:

```text
agr_her_17_geo_armanogeia_1961_dia_3a_3, WCS, GeoTIFF
```

### `default_tags`

Προαιρετικό string ή λίστα από strings. Default: κενό.

Προσθέτει σταθερά tags συμπληρωματικά στα keywords που διαβάζονται από το WMS
`KeywordList`. Τα default tags μπαίνουν στο τέλος του `tag_string`, γίνονται
normalize όπως τα υπόλοιπα WMS tags και δεν διπλοκαταχωρούνται αν υπάρχουν ήδη
στα WMS keywords.

Παράδειγμα:

```json
{
  "default_tags": ["gis", "crete", "INSPIRE", "γεωχωρικά"]
}
```

Με WMS keywords:

```xml
<KeywordList>
  <Keyword>WMS</Keyword>
  <Keyword>INSPIRE</Keyword>
</KeywordList>
```

καταχωρείται:

```text
wms, inspire, gis, crete, γεωχωρικά
```

### `skip_keywords_matching`

Προαιρετικό string ή λίστα από strings. Default: κενό.

Δηλώνει regular expressions για keywords που πρέπει να αγνοηθούν πριν
καταχωρηθούν στο `tag_string`. Οι συγκρίσεις γίνονται case-insensitive και
εφαρμόζονται και στην αρχική τιμή του WMS keyword και στο normalized CKAN tag.

Χρήσιμο για τεχνικά keywords που δεν είναι layer name ακριβώς, αλλά μοιάζουν με
ονόματα views/tables, π.χ.:

```text
v_daokt_cha_elaiourgikoi_foreis
```

Παράδειγμα:

```json
{
  "skip_keywords_matching": ["^v_[a-z0-9_]+$"]
}
```

Με keywords:

```xml
<KeywordList>
  <Keyword>v_daokt_cha_elaiourgikoi_foreis</Keyword>
  <Keyword>WMS</Keyword>
  <Keyword>GeoTIFF</Keyword>
</KeywordList>
```

το πρώτο keyword αγνοείται και καταχωρούνται μόνο:

```text
wms, geotiff
```

Μπορούν να δηλωθούν πολλαπλά patterns:

```json
{
  "skip_keywords_matching": [
    "^v_[a-z0-9_]+$",
    "^tmp_[a-z0-9_]+$",
    "^ckan[-_\\.][a-z0-9_]+$"
  ]
}
```

Αν κάποιο regex είναι άκυρο, αγνοείται και γράφεται warning στο log.

### `skip_dataset_when_title_matches_layer_name`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `true`, ο WMS harvester αγνοεί στο `gather_stage` layers των οποίων
ο τίτλος δεν είναι περιγραφικός αλλά είναι ίδιος με το WMS layer name ή με το
local layer name χωρίς workspace.

Τα `_` και `-` αντιμετωπίζονται ως ισοδύναμα separators, ώστε π.χ. layer
`rym_pireaus:rym_ras_010490FS000349_1932E` να ταιριάζει με τίτλο
`rym_ras_010490FS000349-1932E`.

Παράδειγμα που παραλείπεται:

```xml
<Layer queryable="1" opaque="0">
  <Name>agricultureypaat:agr_her_17_geo_0_a_vatheia_1940_dia_1a_3</Name>
  <Title>agr_her_17_geo_0_a_vatheia_1940_dia_1a_3</Title>
  <Abstract/>
</Layer>
```

Εδώ το `Title` είναι ίδιο με το local layer name:

```text
agr_her_17_geo_0_a_vatheia_1940_dia_1a_3
```

Άρα δεν δημιουργείται `HarvestObject`, δεν περνάει σε `fetch_stage` /
`import_stage`, και δεν δημιουργείται dataset.

Παράδειγμα που δεν παραλείπεται:

```xml
<Layer queryable="1" opaque="0">
  <Name>gisvec:adm_poi_elstat_oikismos</Name>
  <Title>Οικισμοί</Title>
</Layer>
```

Αν ενεργοποιηθεί το flag σε πηγή που είχε ήδη harvested τέτοια layers, τα
skipped layers δεν μπαίνουν στο `guids_in_source`. Άρα στο επόμενο re-harvest
αντιμετωπίζονται ως missing from source και ακολουθούν τη λογική deletion του
harvester.

Παράδειγμα config:

```json
{
  "skip_dataset_when_title_matches_layer_name": true
}
```

### `default_dataset_fields`

Προαιρετικό. Ίδια λογική με τον CSW harvester. Δηλώνει default τιμές για πεδία
του CKAN dataset (`package_dict`).

Παράδειγμα για HVD category:

```json
{
  "default_dataset_fields": {
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"]
  }
}
```

Το παραπάνω καταχωρεί το `hvd_category` σε κάθε WMS-harvested dataset, αν το
πεδίο λείπει ή είναι κενό.

### `override_default_dataset_fields`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `false` ή λείπει, το `default_dataset_fields` δεν αντικαθιστά
υπάρχουσες μη κενές τιμές. Όταν είναι `true`, τις αντικαθιστά.

### `default_resource_fields`

Προαιρετικό. Ίδια λογική με τον CSW harvester. Δηλώνει default τιμές για κάθε
resource που δημιουργεί ο WMS harvester.

Παράδειγμα για άδεια σε όλους τους πόρους:

```json
{
  "default_resource_fields": {
    "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
  }
}
```

Η τιμή εφαρμόζεται σε:

- WMS preview resource,
- WMS capabilities resource,
- WFS capabilities resource.

### `override_default_resource_fields`

Προαιρετικό boolean. Default: `false`.

Όταν είναι `false` ή λείπει, το `default_resource_fields` δεν αντικαθιστά
υπάρχουσες μη κενές τιμές. Όταν είναι `true`, τις αντικαθιστά.

### `preserve_resource_ids_by_url`

Προαιρετικό boolean. Default: `true`.

Ίδια λογική με τον CSW harvester. Στο re-harvest προσπαθεί να διατηρήσει τα
υπάρχοντα CKAN resource ids αντιστοιχίζοντας resources με βάση URL και, όπου
υπάρχει, `resource_locator_protocol` ή `format`.

Για απενεργοποίηση:

```json
{
  "preserve_resource_ids_by_url": false
}
```

### `gather_log_every`

Προαιρετικό integer. Default: `100`.

Ελέγχει κάθε πόσα layers γράφεται progress log στο `gather_stage`.

Ο harvester γράφει πάντα log στο πρώτο και στο τελευταίο layer. Με default:

```text
WMS capabilities gather progress: 100/1675 layer=<layer_name> guid=<guid>
```

Για log σε κάθε layer:

```json
{
  "gather_log_every": 1
}
```

### `timeout`

Προαιρετικό integer. Default: `60`.

Timeout σε δευτερόλεπτα για το HTTP request προς το WMS capabilities URL.

```json
{
  "timeout": 120
}
```

### `user_agent`

Προαιρετικό string. Αν οριστεί, αποστέλλεται ως HTTP `User-Agent` όταν ο
harvester κατεβάζει το WMS capabilities document.

```json
{
  "user_agent": "data.gov.gr CKAN WMS Harvester"
}
```

### Σύγκριση λειτουργιών consent — Analytics vs Privacy

| | `disabled` | `tracking_consent` | `cookie_consent` | `opt_out` |
|---|---|---|---|---|
| **Banner** | Κανένα | Αποδοχή / Απόρριψη | Αποδοχή / Απόρριψη | Εξαίρεση (toggle) |
| **GDPR συμμόρφωση** | Καμία | Πλήρης (αυστηρότερη) | Υψηλή | Χαμηλή (μπορεί να μην αρκεί) |
| **Νομική βάση** | — | Συγκατάθεση (consent) | Συγκατάθεση για cookies, έννομο συμφέρον για ανώνυμα analytics | Έννομο συμφέρον (legitimate interest) |

**Τι χάνετε σε analytics:**

| Μετρική | `disabled` | `tracking_consent` | `cookie_consent` | `opt_out` |
|---|---|---|---|---|
| Pageviews (σύνολο) | 100% | Μόνο από χρήστες που αποδέχτηκαν | 100% | ~100% (ελάχιστοι κάνουν opt-out) |
| Unique visitors | 100% | Μόνο από χρήστες που αποδέχτηκαν | Μόνο από χρήστες που αποδέχτηκαν cookies | ~100% |
| Returning visitors | 100% | Μόνο με consent | Μόνο με consent cookies | ~100% |
| Session duration / bounce rate | 100% | Μόνο με consent | Χωρίς cookies: κάθε pageview = νέα session | ~100% |
| Downloads / events | 100% | Μόνο με consent | 100% | ~100% |
| Referrers / campaigns | 100% | Μόνο με consent | 100% | ~100% |

**Τι κερδίζετε σε privacy:**

| Πτυχή | `disabled` | `tracking_consent` | `cookie_consent` | `opt_out` |
|---|---|---|---|---|
| Καμία αποθήκευση cookies χωρίς συγκατάθεση | — | Ναι | Ναι | Όχι |
| Κανένα tracking χωρίς συγκατάθεση | — | Ναι | Όχι (ανώνυμα requests στέλνονται) | Όχι |
| Δυνατότητα εξαίρεσης χρήστη | — | Ναι (decline) | Ναι (decline cookies) | Ναι (opt-out) |
| Συμμόρφωση ePrivacy Directive (cookie law) | Όχι | Πλήρης | Πλήρης | Αμφίβολη |
| Κατάλληλο για δημόσιο φορέα ΕΕ | Όχι | Ναι | Ναι | Πιθανώς όχι |

> **Σύσταση για δημόσια πύλη:** Η επιλογή `cookie_consent` προσφέρει το καλύτερο
> balance — διατηρεί βασικά analytics (pageviews, downloads, referrers) ακόμα και
> χωρίς αποδοχή, ενώ σέβεται τη νομοθεσία για cookies. Αν ο νομικός σύμβουλος
> απαιτεί αυστηρότερη συμμόρφωση, η `tracking_consent` είναι η ασφαλέστερη
> επιλογή, αλλά με σημαντική απώλεια δεδομένων analytics.


## Developer installation

To install ckanext-data-gov-gr for development, activate your CKAN virtualenv and
do:

    git clone https://github.com//ckanext-data-gov-gr.git
    cd ckanext-data-gov-gr
    pip install -e .
    pip install -r dev-requirements.txt


## Tests

To run the tests, do:

    pytest --ckan-ini=test.ini


## Releasing a new version of ckanext-data-gov-gr

If ckanext-data-gov-gr should be available on PyPI you can follow these steps to publish a new version:

1. Update the version number in the `pyproject.toml` file. See [PEP 440](http://legacy.python.org/dev/peps/pep-0440/#public-version-identifiers) for how to choose version numbers.

2. Make sure you have the latest version of necessary packages:

    pip install --upgrade setuptools wheel twine

3. Create a source and binary distributions of the new version:

       python -m build && twine check dist/*

   Fix any errors you get.

4. Upload the source distribution to PyPI:

       twine upload dist/*

5. Commit any outstanding changes:

       git commit -a
       git push

6. Tag the new release of the project on GitHub with the version number from
   the `setup.py` file. For example if the version number in `setup.py` is
   0.0.1 then do:

       git tag 0.0.1
       git push --tags

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
