# ckanext-hvd-validator

On-demand ελεγκτής DCAT-AP HVD για CKAN.

Το plugin προσθέτει τη σελίδα `/hvd-validator`, όπου ο χρήστης μπορεί να
ελέγξει RDF metadata βάσει DCAT-AP HVD και των αντίστοιχων ευρωπαϊκών SHACL
σχημάτων. Είναι read-only εργαλείο: δεν ενημερώνει CKAN datasets, resources,
πίνακες βάσης ή uploaded RDF αρχεία.

## Τι Ελέγχει

Ο validator ελέγχει RDF metadata απέναντι στο τοπικά ενσωματωμένο αρχείο
`dcat-ap-hvd.shapes.ttl` του ευρωπαϊκού DCAT-AP HVD profile. Ο έλεγχος είναι
δομικός SHACL validation, όχι νομική αξιολόγηση για το αν ένα dataset καλύπτει
πλήρως τον Κανονισμό (ΕΕ) 2023/138.

Γι' αυτό και η διατύπωση στο UI είναι σκόπιμα:

> Ελέγξτε RDF metadata βάσει DCAT-AP HVD και των αντίστοιχων ευρωπαϊκών SHACL
> σχημάτων.

## Τρόποι Εισαγωγής

Η σελίδα υποστηρίζει έναν βασικό τρόπο εισαγωγής και δύο προαιρετικούς. By
default είναι ενεργό μόνο το `Dataset name / UUID`, ώστε το εργαλείο να
ελέγχει RDF που παράγεται από το ίδιο CKAN instance.

### Όνομα Dataset Ή UUID

Η φόρμα για αυτό το mode υποβάλλεται με HTTP GET:

```text
/hvd-validator?input_mode=name&dataset_name=<name-or-uuid>
```

Το plugin καλεί in-process το CKAN action `dcat_dataset_show` για το dataset:

```python
toolkit.get_action("dcat_dataset_show")(context, {"id": name, "format": "rdf"})
```

Το `context` περιλαμβάνει τον τρέχοντα authenticated χρήστη, άρα το εσωτερικό
`package_show` εφαρμόζει τα CKAN permissions. Έτσι ο χρήστης μπορεί να ελέγξει
private dataset μόνο αν έχει πράγματι πρόσβαση σε αυτό, π.χ. ως sysadmin ή ως
μέλος του οργανισμού που το κατέχει.

Αυτός ο τρόπος προορίζεται για έλεγχο datasets του ίδιου CKAN instance και δεν
κάνει HTTP fetch στο public RDF endpoint.

### Dataset View Action

Το plugin μπορεί να εμφανίζει κουμπί `HVD Validator` στη σελίδα προβολής ενός
dataset όταν το dataset έχει τουλάχιστον μία HVD κατηγορία. Το κουμπί οδηγεί
απευθείας στο `Dataset name / UUID` mode:

```text
/hvd-validator?input_mode=name&dataset_name=<dataset-name>
```

Η εμφάνιση του κουμπιού ελέγχεται με:

```ini
ckanext.hvd_validator.dataset_action.enabled = true
ckanext.hvd_validator.dataset_action.hvd_category_field = hvd_category
ckanext.hvd_validator.dataset_action.package_types = dataset
```

Οι παραπάνω τιμές είναι τα defaults. Το κουμπί εμφανίζεται μόνο σε χρήστες που
έχουν πρόσβαση στο `/hvd-validator`.

Η ρύθμιση `ckanext.hvd_validator.dataset_action.enabled` μπορεί επίσης να
αλλάξει από τη σελίδα `/ckan-admin/config`, αν το admin config template του
plugin συμμετέχει στην ενεργή CKAN template inheritance αλυσίδα.

### RDF URL

Το plugin κατεβάζει ένα οποιοδήποτε HTTP(S) URL και προσπαθεί να το κάνει parse
ως RDF. Το RDF format μαντεύεται από την κατάληξη του URL και το response
content type.

Η φόρμα για αυτό το mode υποβάλλεται με HTTP POST.

Αυτός ο τρόπος είναι disabled by default. Ενεργοποιείται μόνο με:

```ini
ckanext.hvd_validator.input.url.enabled = true
```

### Upload RDF Αρχείου

Η φόρμα για αυτό το mode υποβάλλεται με HTTP POST.

Αυτός ο τρόπος είναι disabled by default. Ενεργοποιείται μόνο με:

```ini
ckanext.hvd_validator.input.file.enabled = true
```

Το plugin δέχεται τις παρακάτω καταλήξεις:

```text
.rdf, .ttl, .xml, .jsonld, .json-ld, .n3, .nt
```

Το UI εμφανίζει τις πιο συνηθισμένες:

```text
.rdf, .ttl, .xml, .jsonld, .n3, .nt
```

Το server-side όριο upload είναι 5 MiB:

```python
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
```

Το αρχείο διαβάζεται στη μνήμη και μετά απορρίπτεται αν το byte size του
ξεπερνά αυτό το όριο.

## Ανίχνευση RDF Format

Η `_guess_format()` αντιστοιχίζει filenames, URLs και content types σε rdflib
parser formats:

| Input | rdflib format |
| --- | --- |
| `.rdf`, `.xml`, default | `xml` |
| `.ttl` ή turtle content type | `turtle` |
| `.jsonld`, `.json-ld` ή JSON content type | `json-ld` |
| `.n3` | `n3` |
| `.nt` | `nt` |

## Validation Pipeline

Η ροή του validation είναι:

1. Fetch ή read RDF.
2. Parse σε in-memory `rdflib.Graph`.
3. Προσωρινός εμπλουτισμός του graph με επιλεγμένα referenced vocabulary
   resources.
4. Εκτέλεση `pyshacl.validate()` απέναντι στο `dcat-ap-hvd.shapes.ttl`.
5. Ταξινόμηση των SHACL results σε violations και warnings.
6. Υπολογισμός display flags και license status.
7. Εμφάνιση μεταφρασμένης σελίδας αποτελεσμάτων.

Η κλήση στο pySHACL είναι:

```python
pyshacl.validate(
    graph,
    shacl_graph=_HVD_SHAPES_TTL,
    shacl_graph_format="turtle",
    advanced=True,
    inference="rdfs",
    debug=False,
)
```

Η τιμή `conforms` επιστρέφεται απευθείας από το pySHACL.

## Εμπλουτισμός Vocabulary

Πριν το SHACL validation, το plugin εμπλουτίζει προσωρινά το in-memory RDF
graph με RDF που κατεβάζει από επιλεγμένα URI references που υπάρχουν ήδη στο
graph:

```python
dcatap:hvdCategory
dcat:accessService
dct:license
```

Για κάθε `URIRef` που βρίσκεται μέσω αυτών των properties, το plugin επιχειρεί
HTTP GET με:

```text
Accept: application/rdf+xml
User-Agent: CKAN-HVD-Validator/1.0
```

Πριν από κάθε external HTTP request εφαρμόζεται SSRF guard. Επιτρέπονται μόνο
`http` και `https` URLs, γίνεται DNS resolution του hostname, και μπλοκάρονται
targets που δείχνουν σε private, loopback, link-local, multicast, reserved ή
unspecified IP addresses. Τα redirects ακολουθούνται χειροκίνητα και κάθε
redirect target περνάει από τον ίδιο έλεγχο πριν γίνει request.

Τα external fetches διαβάζονται με όριο response body 2 MiB. Αν ένα optional
vocabulary response ξεπεράσει το όριο, αγνοείται και το validation συνεχίζει με
το αρχικό graph. Αν το explicit `RDF URL` mode είναι ενεργό και το RDF document
ξεπεράσει το όριο, εμφανίζεται user-facing error.

Τα optional vocabulary fetches έχουν μικρότερο timeout 5s. Το explicit `RDF
URL` mode, αν ενεργοποιηθεί, διατηρεί timeout 30s.

Το vocabulary augmentation κάνει fetch έως 20 unique referenced URIs ανά
validation. Αν υπάρχουν περισσότερα refs, τα υπόλοιπα αγνοούνται ώστε ένα
dataset RDF να μη δημιουργεί μεγάλο request fan-out.

Αν το URI επιστρέψει RDF/XML, το RDF γίνεται parse και merge στο graph. Αν το
URI δεν απαντήσει, δεν μπορεί να γίνει parse ή δεν είναι HTTP RDF document, η
αποτυχία αγνοείται και το validation συνεχίζει με το αρχικό graph.

Τα fetched vocabulary graphs κρατιούνται σε in-memory cache για όσο ζει το CKAN
process.

### Γιατί Γίνεται Augment Το `hvdCategory`

Το RDF ενός dataset συνήθως αναφέρει την HVD κατηγορία ως URI. Τα triples που
αποδεικνύουν ότι το URI είναι `skos:Concept` στο αναμενόμενο HVD scheme μπορεί
να βρίσκονται στο εξωτερικό EU vocabulary document. Το augment αποφεύγει false
SHACL violations για έγκυρα HVD category URIs.

### Γιατί Γίνεται Augment Το `dct:license`

Canonical EU license URIs, όπως:

```text
http://publications.europa.eu/resource/authority/licence/CC_BY_4_0
```

μπορεί να χρειάζονται τα δικά τους RDF vocabulary triples, όπως
`skos:exactMatch`, `owl:sameAs` ή σχετικά mappings, για τα HVD SHACL license
vocabulary checks. Αυτή είναι η ίδια διόρθωση που υπάρχει και στο communication
dashboard.

### Τι Γίνεται Με Το `accessService`

Για `dcat:accessService`, το plugin κάνει fetch το service URI μόνο ως
προαιρετικό augment. Δεν απαιτεί το URI να είναι dereferenceable αν το
`dcat:DataService` περιγράφεται ήδη μέσα στο RDF graph.

Για παράδειγμα, το παρακάτω αρκεί ώστε το SHACL να δει το service:

```xml
<dcat:Distribution>
  <dcat:accessService rdf:resource="https://example.gov/access-service"/>
</dcat:Distribution>

<dcat:DataService rdf:about="https://example.gov/access-service">
  <dcat:endpointURL>
    <rdfs:Resource rdf:about="https://example.gov/api/3/action/datastore_search"/>
  </dcat:endpointURL>
</dcat:DataService>
```

Αν το `https://example.gov/access-service` δεν επιστρέψει RDF μέσω HTTP, ο
validator εξακολουθεί να χρησιμοποιεί τα inline `dcat:DataService` triples που
υπάρχουν ήδη στο uploaded/fetched graph.

## Ταξινόμηση Αποτελεσμάτων

Το plugin διαβάζει το SHACL results graph και παράγει:

| Field | Σημασία |
| --- | --- |
| `conforms` | αποτέλεσμα συμμόρφωσης από pySHACL |
| `violation_count` | πλήθος SHACL violations |
| `warning_count` | πλήθος SHACL warnings |
| `legal_citation_issue` | true για applicable-legislation violations σε dataset/distribution |
| `no_api_access` | true μόνο όταν αποτυγχάνει το HVD API MinCount shape |
| `license_status` | license status που υπολογίζει το plugin |
| `details` | deduplicated λίστα violations και warnings |

Το `legal_citation_issue` μπαίνει μόνο για violations σε `DatasetShape` ή
`DistributionShape` πάνω στο `applicableLegislation`. Τα κενά νομοθεσίας σε
`DataService` είναι πραγματικά SHACL findings, αλλά δεν ταξινομούνται ως
πρόβλημα της νομοθετικής αναφοράς του ίδιου του dataset.

Το `no_api_access` μπαίνει μόνο όταν αποτυγχάνει το σταθερό
`DatasetShape/API` MinCount constraint. Ένα blank-node/inline service μπορεί να
παράγει διαφορετικό SHACL finding, αλλά δεν ταξινομείται ως "no API access".

## License Status

Το plugin υπολογίζει ξεχωριστό display-oriented license status από τις τιμές
`dct:license`:

| Internal value | UI label | Σημασία |
| --- | --- | --- |
| `missing` | Missing / Λείπει | Δεν βρέθηκε `dct:license` |
| `open` | Open / Ανοικτή | Το license URI ταιριάζει σε γνωστούς open-license markers |
| `non_open` | Not confirmed open / Δεν επιβεβαιώθηκε ως ανοικτή | Δεν επιβεβαιώθηκε ως ανοικτή άδεια από το marker check |

Αυτό δεν είναι πλήρης νομική ανάλυση άδειας. Το `non_open` σημαίνει ότι το
plugin δεν επιβεβαίωσε την άδεια ως ανοικτή με βάση τους γνωστούς markers.

## Κατανοητά SHACL Μηνύματα

Τα raw pySHACL messages είναι συχνά υπερβολικά τεχνικά για τελικούς χρήστες.
Το plugin χαρτογραφεί γνωστά SHACL findings σε πιο κατανοητά μηνύματα και τα
μεταφράζει μέσω του CKAN i18n συστήματος.

Ειδικές περιπτώσεις:

| Τεχνική συνθήκη | Κατανοητό μήνυμα |
| --- | --- |
| `applicableLegislation` + class constraint | Η νομοθεσία που αναφέρεται δεν συνδέεται με αναγνωρισμένο νομικό πόρο της ΕΕ (ELI). |
| άλλο issue σε `applicableLegislation` | Η εφαρμοστέα HVD νομοθεσία δεν αναφέρεται ως σωστά συνδεδεμένος νομικός πόρος. |
| `accessService` + min count | Δεν έχει συνδεθεί API/data access service με το dataset. |
| `accessService` + class constraint | Έχει συνδεθεί API, αλλά δεν περιγράφεται ως `dcat:DataService`. |
| `accessService` + node kind constraint | Έχει συνδεθεί API inline, αλλά δεν έχει δική του σταθερή web διεύθυνση. |
| license vocabulary match warning | Η άδεια δεν μπόρεσε να αντιστοιχιστεί με γνωστή ανοικτή άδεια στο λεξιλόγιο της ΕΕ. |

Γενικές περιπτώσεις:

| SHACL constraint | Pattern κατανοητού μηνύματος |
| --- | --- |
| `MinCountConstraintComponent` | `Missing {label}.` |
| `NodeKindConstraintComponent` | `{label} isn't a properly linked resource (a plain value instead of a URI).` |
| `ClassConstraintComponent` | `{label} doesn't reference the expected type of resource.` |
| `DatatypeConstraintComponent` | `{label} has the wrong data type.` |
| οποιοδήποτε άλλο γνωστό path | `Issue with {label}.` |

Γνωστά RDF property labels:

| RDF local name | Label |
| --- | --- |
| `applicableLegislation` | applicable EU legislation citation |
| `hvdCategory` | HVD category classification |
| `servesDataset` | link back to the dataset this API serves |
| `endpointURL` | API endpoint URL |
| `endpointDescription` | API endpoint documentation |
| `contactPoint` | dataset contact point |
| `page` | documentation/reference page |
| `rights` | rights statement |
| `license` | license |
| `conformsTo` | standard/specification it conforms to |
| `distribution` | at least one distribution |
| `inSeries` | dataset series it belongs to |
| `hasEmail` | contact point email address |
| `hasURL` | contact point web address |
| `inScheme` | vocabulary/scheme reference |
| `accessService` | linked API/access service |
| `accessURL` | API access URL |

Αν δεν υπάρχει mapping, εμφανίζεται το raw SHACL message.

## Μεταφράσεις

Το plugin υλοποιεί CKAN `ITranslation`.

Οι ελληνικές μεταφράσεις βρίσκονται στο:

```text
ckanext/hvd_validator/i18n/el/LC_MESSAGES/ckanext-hvd_validator.po
```

Το compiled catalog είναι tracked στο:

```text
ckanext/hvd_validator/i18n/el/LC_MESSAGES/ckanext-hvd_validator.mo
```

Χειροκίνητο compile:

```bash
msgfmt -o ckanext/hvd_validator/i18n/el/LC_MESSAGES/ckanext-hvd_validator.mo \
  ckanext/hvd_validator/i18n/el/LC_MESSAGES/ckanext-hvd_validator.po
```

Το communication dashboard είχε την ίδια friendly-message λογική hardcoded στα
Αγγλικά μέσα στο `app.py`. Το plugin χρησιμοποιεί gettext, ώστε το UI να μπορεί
να εμφανίζει αυτά τα μηνύματα στα Ελληνικά.

## Εγκατάσταση

Εγκατάσταση στο CKAN virtualenv:

```bash
pip install -e 'git+https://git.example.org/example-org/ckanext-hvd-validator.git@main#egg=ckanext-hvd-validator'
```

Ενεργοποίηση στο `ckan.ini`:

```ini
ckan.plugins = ... hvd_validator ...
```

Προαιρετική ενεργοποίηση των πιο ανοιχτών input modes:

```ini
ckanext.hvd_validator.input.url.enabled = false
ckanext.hvd_validator.input.file.enabled = false
```

Οι παραπάνω τιμές είναι τα defaults. Αλλάξτε τις σε `true` μόνο αν θέλετε το
εργαλείο να δέχεται arbitrary RDF URL ή RDF file upload.

Το σχετικό `ckanext-data-gov-gr` plugin ελέγχει αν η σελίδα `/more` εμφανίζει
κάρτα για αυτό το εργαλείο μέσω:

```ini
ckanext.data_gov_gr.more.hvd_validator.enabled = true
```

Στο staging setup του data.gov.gr, το `install-plugins` εγκαθιστά αυτό το
plugin από το branch `main`.

## Πρόσβαση

Η σελίδα `/hvd-validator` δεν είναι public. Πρόσβαση έχουν μόνο:

- sysadmins
- authenticated χρήστες που έχουν οποιονδήποτε ρόλο σε τουλάχιστον έναν
  οργανισμό CKAN (`member`, `editor` ή `admin`)

Οι anonymous χρήστες ανακατευθύνονται στο login. Authenticated χρήστες χωρίς
ρόλο σε οργανισμό παίρνουν 403.

Η κάρτα στη σελίδα `/more` πρέπει να εμφανίζεται με τον ίδιο κανόνα πρόσβασης.
Στο data.gov.gr αυτό γίνεται από το `ckanext-data-gov-gr`, το οποίο κάνει
optional import του canonical access helper από το `ckanext-hvd-validator`.

## Λειτουργικές Σημειώσεις

- Το validation είναι on-demand και τρέχει μέσα στο request του χρήστη.
- By default είναι διαθέσιμο μόνο το input mode `Dataset name / UUID`.
- Το `Dataset name / UUID` mode χρησιμοποιεί GET, ώστε refresh/back να μη
  ξαναϋποβάλλει POST φόρμα στον browser.
- Σε HVD datasets μπορεί να εμφανιστεί κουμπί `HVD Validator` στη σελίδα
  προβολής του dataset, το οποίο ανοίγει απευθείας το GET validation flow.
- Τα input modes `RDF URL` και `Upload RDF file` είναι κλειστά εκτός αν
  ενεργοποιηθούν ρητά από config.
- Τα `RDF URL` και `Upload RDF file` modes παραμένουν POST flows όταν
  ενεργοποιηθούν.
- Η rendered validator σελίδα επιστρέφει `Cache-Control: private, no-cache`.
- Το SHACL validation μπορεί να διαρκέσει μερικά δευτερόλεπτα.
- Δεν χρησιμοποιούνται database tables ή persistent cache.
- Το vocabulary RDF cache είναι in-memory ανά CKAN process.
- Αποτυχίες σε external vocabulary fetch αγνοούνται.
- Τα external fetches περνούν από SSRF guard που μπλοκάρει local/private
  network targets και unsafe redirects.
- Τα external fetches έχουν μέγιστο response body 2 MiB.
- Το vocabulary augmentation κάνει fetch έως 20 unique referenced URIs ανά validation.
- Τα optional vocabulary fetches έχουν timeout 5s, ενώ τα explicit URL fetches 30s.
- Τα URL fetches δεν κάνουν αυτόματο retry. Ο χρήστης μπορεί να ξαναπατήσει Validate.
- Το upload size ελέγχεται αφού το αρχείο διαβαστεί στη μνήμη.
- Τα validation errors γίνονται catch και εμφανίζονται ως user-facing errors
  αντί για CKAN 500 page.

## Σχέση Με Το Communication Dashboard

Ο validation core εξήχθη από το HVD check του communication dashboard. Κοινή
λογική:

- DCAT-AP HVD SHACL shapes.
- Vocabulary augmentation για HVD category, access service και license URI.
- SHACL result classification.
- Κατανοητά SHACL finding messages.
- License status detection.

Dashboard-only λογική που δεν μπήκε σκόπιμα:

- Bulk scheduled checks.
- Database caching αποτελεσμάτων.
- Progress/cancellation state.
- CKAN organization grouping.
- Publisher mismatch heuristic.
- Excel export.
- Retry του dataset RDF fetch για μεγάλα bulk runs.

Το retry έχει νόημα στο dashboard επειδή ελέγχει πολλά datasets σε ένα burst.
Στο plugin το validation είναι single-request και ο χρήστης μπορεί να πατήσει
ξανά Validate αν υπάρξει προσωρινό network failure.
