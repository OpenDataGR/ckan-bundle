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
