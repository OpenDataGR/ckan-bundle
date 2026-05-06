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
    "hvd_category": ["http://data.europa.eu/bna/c_ac64a52d"]
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
  "wms_preview_from_online_resource": true,
  "wms_preview_base_url": "https://gis.piraeus.gov.gr/geoserver/wms#",
  "preserve_resource_ids_by_url": true,
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

Η τιμή εφαρμόζεται μόνο για INSPIRE
`ConditionsApplyingToAccessAndUse` anchors. Για παράδειγμα:

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
