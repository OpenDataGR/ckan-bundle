# OAI-PMH DCAT-AP Harvester

Αυτό το αρχείο τεκμηριώνει τον νέο harvester:

```text
ckanext/data_gov_gr/harvesters/oai_pmh_dcat_harvester.py
```

Plugin name:

```text
oai_pmh_dcat_harvester
```

Σκοπός του harvester είναι να διαβάζει OAI-PMH endpoints που επιστρέφουν
DCAT-AP RDF/XML μέσα σε OAI-PMH `ListRecords` responses και να τα καταχωρεί ως
CKAN datasets.

## Τι πρόβλημα λύνει

Υπάρχουν πηγές, όπως το RAISE, που δεν δίνουν ένα απλό DCAT catalog URL. Αντί
για αυτό δίνουν OAI-PMH endpoint:

```text
https://develop.api.portal.raise-science.eu/oai/user/<catalog-id>
```

και τα datasets τα παίρνουμε με request:

```text
?verb=ListRecords&metadataPrefix=dcat_ap
```

Το response δεν είναι απλό DCAT RDF. Είναι OAI-PMH XML envelope που μέσα σε κάθε
`<record>` έχει DCAT RDF/XML:

```xml
<record>
  <header>
    <identifier>oai:raise:...</identifier>
    <datestamp>2026-01-23</datestamp>
  </header>
  <metadata>
    <rdf:RDF>
      <dcat:Dataset>...</dcat:Dataset>
      <dcat:Distribution>...</dcat:Distribution>
    </rdf:RDF>
  </metadata>
</record>
```

Οι υπάρχοντες DCAT harvesters ξέρουν να διαβάζουν RDF/DCAT, αλλά όχι OAI-PMH
wrapper. Το παλιό `https://github.com/DataShades/ckanext-oaipmh` ξέρει OAI-PMH, αλλά κάνει mapping για
`oai_dc` / `oai_ddi`, όχι για DCAT-AP. Ο νέος harvester είναι το adapter:

```text
OAI-PMH ListRecords -> rdf:RDF payload -> ckanext-dcat RDFParser -> CKAN package dict
```

## Τι πήραμε από το παλιό ckanext-oaipmh

Από το `/root/ckanext-oaipmh` κρατήθηκε κυρίως η λογική του OAI-PMH transport:

- το harvest source URL είναι το base OAI-PMH endpoint,
- το metadata format δηλώνεται με `metadata_prefix`,
- το `set` είναι προαιρετικό filter και μπαίνει μόνο αν δηλωθεί,
- `username` / `password` μπορούν να χρησιμοποιηθούν για HTTP credentials,
- το OAI-PMH endpoint μπορεί να επιστρέφει πολλά records σε περισσότερες από μία
  σελίδες.

Δεν κρατήθηκε το παλιό metadata mapping, γιατί εκείνο ήταν για `oai_dc` και
`oai_ddi`. Εδώ το metadata payload είναι DCAT-AP RDF/XML, άρα το parsing γίνεται
με `ckanext-dcat`.

## Πώς ενεργοποιείται

Ο harvester δηλώνεται στα entry points στο `pyproject.toml`:

```toml
oai_pmh_dcat_harvester = "ckanext.data_gov_gr.harvesters.oai_pmh_dcat_harvester:OaiPmhDcatHarvester"
```

Στο CKAN πρέπει να είναι ενεργός μαζί με το harvest extension:

```ini
ckan.plugins = ... harvest oai_pmh_dcat_harvester ...
```

Αν έχει προστεθεί πρόσφατα στα entry points, χρειάζεται editable install και
restart των CKAN / harvest worker processes:

```bash
cd /root/ckan/lib/default/src/ckanext-data-gov-gr
/usr/lib/ckan/default/bin/pip install -e .
```

## Harvest source URL

Στο harvest source URL μπαίνει το base endpoint, χωρίς query params:

```text
https://develop.api.portal.raise-science.eu/oai/user/0f868393-e7b7-49c2-9a2b-5421b6fbd266
```

Ο harvester χτίζει μόνος του το request:

```text
?verb=ListRecords&metadataPrefix=dcat_ap
```

Για local debugging μπορεί να μπει path προς XML αρχείο:

```text
/root/OAI-PMH/0f868393-e7b7-49c2-9a2b-5421b6fbd266.xml
```

Σε αυτή την περίπτωση το αρχείο διαβάζεται ως bytes, για να μη χαλάσει το UTF-8
encoding των ελληνικών.

## Παράδειγμα configuration

Το config μπαίνει στο JSON configuration του harvest source, όχι στο `ckan.ini`.

```json
{
  "metadata_prefix": "dcat_ap",
  "rdf_format": "xml",
  "dataset_name_prefix_from_identifier": "raise-",
  "dataset_name_max_length": 100,
  "timeout": 60,
  "user_agent": "data.gov.gr OAI-PMH DCAT Harvester"
}
```

Για full harvest χωρίς ειδικά filters, τα βασικά είναι:

```json
{
  "metadata_prefix": "dcat_ap",
  "rdf_format": "xml"
}
```

## Συνολική ροή εκτέλεσης

Όταν τρέχει ένα harvest job:

1. Το CKAN καλεί το `gather_stage`.
2. Ο harvester διαβάζει το JSON config του harvest source.
3. Χτίζει OAI-PMH `ListRecords` URL.
4. Κατεβάζει το XML response ή διαβάζει local XML file.
5. Για κάθε OAI-PMH `<record>`:
   - παίρνει `header/identifier`,
   - παίρνει `header/datestamp`,
   - παίρνει το `<metadata><rdf:RDF>...</rdf:RDF></metadata>`,
   - το περνά στον `RDFParser`,
   - παίρνει CKAN dataset dict.
6. Προετοιμάζει το dataset:
   - φτιάχνει `name`,
   - βάζει `owner_org` από το harvest source,
   - βάζει `metadata_modified` από το OAI datestamp αν χρειάζεται,
   - συμπληρώνει fallback resource names.
7. Υπολογίζει harvest `guid`.
8. Δημιουργεί `HarvestObject` με JSON content το parsed dataset dict.
9. Αν υπάρχει `resumptionToken`, ζητά την επόμενη OAI-PMH page.
10. Στο τέλος σημαδεύει για deletion datasets που υπήρχαν σε προηγούμενο harvest
    αλλά δεν εμφανίστηκαν στο τρέχον source.
11. Το `fetch_stage` επιστρέφει `True`, γιατί το record έχει ήδη γίνει fetch στο
    gather.
12. Το import γίνεται από το inherited `CustomDcatHarvester` /
    `DCATRDFHarvester` flow.

## Πού αναλαμβάνει δράση το DCAT harvester / parser

Υπάρχουν δύο διαφορετικά σημεία όπου μπαίνει η DCAT λογική.

### 1. Στο parsing του RDF/XML

Το πρώτο σημείο είναι μέσα στον δικό μας harvester, στη μέθοδο:

```python
def _parse_rdf_dataset(self, rdf_xml, config):
```

Μέχρι εκείνο το σημείο ο `oai_pmh_dcat_harvester` έχει κάνει μόνο το OAI-PMH
κομμάτι:

- έχει κατεβάσει το `ListRecords` XML,
- έχει βρει κάθε `<record>`,
- έχει πάρει από μέσα το `<metadata><rdf:RDF>...</rdf:RDF></metadata>`.

Το κρίσιμο πέρασμα είναι:

```python
parser = RDFParser()
parser.parse(rdf_xml, _format=config.get("rdf_format") or self.DEFAULT_RDF_FORMAT)

for dataset in parser.datasets():
    return dataset or None
```

Εδώ αναλαμβάνει ο `ckanext-dcat` `RDFParser`.

Αυτός μετατρέπει το DCAT RDF/XML σε CKAN package dict.

Δηλαδή από RDF/XML τύπου:

```xml
<dct:title>...</dct:title>
<dct:description>...</dct:description>
<dcat:keyword>...</dcat:keyword>
<dcat:distribution>...</dcat:distribution>
```

παίρνουμε Python dict περίπου σαν:

```python
{
    "title": "...",
    "notes": "...",
    "url": "...",
    "tags": [...],
    "resources": [...],
    "extras": [...]
}
```

Άρα εδώ γίνεται ο βασικός μετασχηματισμός:

```text
DCAT RDF/XML -> CKAN dataset dict
```

Ο OAI-PMH harvester δεν κάνει χειροκίνητο mapping των DCAT πεδίων. Δεν γράφει
μόνος του π.χ. `dct:title -> title` ή `dcat:Distribution -> resources`. Αυτό το
κάνει ο `RDFParser` του `ckanext-dcat`.

### 2. Στο import / normalization flow

Το δεύτερο σημείο είναι μετά το gather, όταν το CKAN harvest pipeline περνά στο
import.

Ο νέος harvester κληρονομεί από:

```python
class OaiPmhDcatHarvester(CustomDcatHarvester):
```

και δεν ορίζει δικό του `import_stage`. Άρα χρησιμοποιείται το import flow που
έρχεται από το `CustomDcatHarvester` / `DCATRDFHarvester`.

Σε εκείνη τη φάση το `HarvestObject.content` έχει ήδη το parsed CKAN package dict
σε JSON μορφή. Το inherited import flow το παίρνει και εφαρμόζει τα data.gov.gr
normalization rules, όπως:

- controlled vocabularies,
- themes,
- licenses,
- access rights,
- multilingual fields,
- resource cleanup,
- schema compatibility,
- `package_create` ή `package_update`.

Άρα η πλήρης αλυσίδα είναι:

```text
OAI-PMH ListRecords XML
  -> oai_pmh_dcat_harvester βγάζει το rdf:RDF από κάθε record
  -> ckanext-dcat RDFParser μετατρέπει RDF/XML σε CKAN package dict
  -> oai_pmh_dcat_harvester το αποθηκεύει σε HarvestObject.content
  -> CustomDcatHarvester / DCATRDFHarvester import flow κάνει normalization και create/update
```

Το πιο σημαντικό σημείο του κώδικα είναι:

```python
dataset = self._parse_rdf_dataset(rdf_xml, config)
```

Εκεί περνάμε από "OAI-PMH record που περιέχει DCAT RDF" σε "CKAN dataset dict".

## Imports και σταθερές

Ο harvester χρησιμοποιεί:

- `requests` για HTTP GET προς το OAI-PMH endpoint,
- `lxml.etree` για XML parsing,
- `RDFParser` από `ckanext-dcat` για DCAT RDF/XML parsing,
- `HarvestObject` και `HarvestObjectExtra` από `ckanext-harvest`,
- `CustomDcatHarvester` ώστε να ξαναχρησιμοποιήσει τα data.gov.gr normalization
  hooks.

Βασικές σταθερές:

```python
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/"}
DATASET_NAME_PREFIX_FROM_IDENTIFIER_CONFIG_KEY = "dataset_name_prefix_from_identifier"
DATASET_NAME_MAX_LENGTH_CONFIG_KEY = "dataset_name_max_length"
DEFAULT_DATASET_NAME_MAX_LENGTH = 100
```

Το `OAI_NS` χρειάζεται για XPath queries πάνω στο OAI-PMH XML, επειδή τα στοιχεία
`OAI-PMH`, `ListRecords`, `record`, `header` κ.λπ. είναι namespaced.

Το `UUID_RE` βρίσκει UUIDs μέσα σε strings όπως:

```text
10.83613/raise-dev/dataset/08dea5d9-7569-4bfd-8563-5c30372a3ef9
```

## `normalize_ckan_name`

Η helper function:

```python
def normalize_ckan_name(value):
```

μετατρέπει ένα string σε CKAN-safe dataset name:

- κάνει unicode normalization,
- κρατά μόνο ASCII χαρακτήρες,
- κάνει lowercase,
- αντικαθιστά μη επιτρεπτούς χαρακτήρες με `-`,
- συμπτύσσει πολλαπλά `---`,
- κόβει αρχικά/τελικά `-` και `_`.

Χρησιμοποιείται στη λογική:

```text
dataset_name_prefix_from_identifier + uuid
```

Παράδειγμα:

```text
RAISE 08DEA5D9... -> raise-08dea5d9-...
```

## Κλάση `OaiPmhDcatHarvester`

Η κλάση:

```python
class OaiPmhDcatHarvester(CustomDcatHarvester):
```

κληρονομεί από `CustomDcatHarvester`. Αυτό είναι σημαντικό γιατί θέλουμε το
τελικό import να περάσει από τα ίδια data.gov.gr fixes που χρησιμοποιούνται και
στους DCAT harvesters:

- controlled vocabularies,
- licenses,
- access rights,
- multilingual fields,
- resources normalization,
- schema compatibility.

Τα defaults της κλάσης είναι:

```python
DEFAULT_METADATA_PREFIX = "dcat_ap"
DEFAULT_RDF_FORMAT = "xml"
DEFAULT_TIMEOUT = 60
```

## `__new__`

```python
def __new__(cls, *args, **kwargs):
```

Υπάρχει λόγω CKAN plugin singleton συμπεριφοράς.

Το `CustomDcatHarvester` είναι επίσης `SingletonPlugin`. Αν έχει ήδη φορτωθεί
άλλος harvester που κληρονομεί από την ίδια βάση, υπάρχει κίνδυνος να
ξαναχρησιμοποιηθεί λάθος `_instance`. Το `__new__` εξασφαλίζει ότι η
`OaiPmhDcatHarvester` έχει δικό της instance.

## `info`

```python
def info(self):
```

Δηλώνει στο CKAN harvest UI τα βασικά metadata του harvester:

- internal name: `oai_pmh_dcat_harvester`,
- title: `OAI-PMH DCAT-AP Harvester`,
- description,
- config UI ως απλό text JSON.

Αυτό είναι που βλέπει το CKAN όταν επιλέγεις source type.

## `validate_config`

```python
def validate_config(self, source_config):
```

Ελέγχει το JSON config του harvest source όταν αποθηκεύεται.

Αν το config είναι κενό, επιστρέφει defaults:

```json
{
  "metadata_prefix": "dcat_ap",
  "rdf_format": "xml"
}
```

Αν υπάρχει config:

1. Προσπαθεί να το κάνει `json.loads`.
2. Απαιτεί να είναι JSON object.
3. Ελέγχει ότι κάποια fields είναι strings:
   - `metadata_prefix`,
   - `rdf_format`,
   - `set`,
   - `from`,
   - `until`,
   - `user_agent`,
   - `dataset_name_prefix_from_identifier`.
4. Ελέγχει ότι κάποια fields είναι θετικοί ακέραιοι:
   - `timeout`,
   - `dataset_name_max_length`.

Σημείωση: κάποια runtime-only options όπως `max_pages` και `throttle_ms`
χρησιμοποιούνται στο gather, αλλά αυτή τη στιγμή δεν ελέγχονται εδώ. Αν θέλουμε
πιο αυστηρό validation, μπορούν να προστεθούν.

## `gather_stage`

```python
def gather_stage(self, harvest_job):
```

Είναι το βασικό στάδιο του harvester.

Στους περισσότερους CKAN harvesters το gather απλώς βρίσκει identifiers και το
fetch κατεβάζει κάθε record. Εδώ κάνουμε το full fetch ήδη στο gather, γιατί το
`ListRecords` response περιέχει και το metadata payload.

### Αρχικοποίηση

```python
config = self._config(harvest_job)
harvest_local.user_agent = config.get("user_agent")
object_ids = []
guids_in_source = []
self._names_taken = []
```

Εδώ:

- διαβάζεται το config,
- περνά το `user_agent` στο shared DCAT harvest local context,
- αρχικοποιείται λίστα με τα νέα `HarvestObject` ids,
- αρχικοποιείται λίστα με τα guids που υπάρχουν στην τρέχουσα πηγή,
- μηδενίζεται η λίστα names που έχουν ήδη χρησιμοποιηθεί στο ίδιο gather.

### Source dataset και υπάρχοντα guid mappings

```python
source_dataset = model.Package.get(harvest_job.source.id)
guid_to_package_id = self._existing_guid_to_package_id(harvest_job)
```

Το `source_dataset` είναι το CKAN package που αντιστοιχεί στο harvest source. Από
αυτό παίρνουμε κυρίως:

- `owner_org`,
- `name`,
- `url`.

Το `guid_to_package_id` λέει ποια harvested datasets υπάρχουν ήδη από
προηγούμενο harvest της ίδιας source. Έτσι ξέρουμε αν ένα record είναι:

- `new`,
- ή `change`.

### Πρώτο OAI-PMH URL

```python
next_url = self._build_oai_url(harvest_job.source.url, config)
```

Αν το source URL είναι:

```text
https://example.test/oai
```

και το config:

```json
{"metadata_prefix": "dcat_ap"}
```

τότε φτιάχνεται:

```text
https://example.test/oai?verb=ListRecords&metadataPrefix=dcat_ap
```

### Loop πάνω στις OAI-PMH pages

```python
while next_url:
```

Ο harvester διαβάζει μία ή περισσότερες OAI-PMH pages. Περισσότερες υπάρχουν όταν
το endpoint επιστρέψει `resumptionToken`.

Αν έχει δηλωθεί:

```json
{"max_pages": 1}
```

τότε σταματά μετά την πρώτη page. Αυτό είναι δική μας δοκιμαστική επιλογή, όχι
OAI-PMH parameter.

### Φόρτωση XML

```python
content = self._load_oai_page(next_url, harvest_job, config)
```

Αν το URL είναι HTTP, κάνει GET. Αν είναι local path, διαβάζει το αρχείο.

Το αποτέλεσμα είναι bytes, όχι decoded text. Αυτό αποφεύγει encoding bugs όπου
ελληνικά UTF-8 διαβάζονται σαν latin-1 και εμφανίζονται ως `Î...`.

### Parsing OAI-PMH page

```python
records, resumption_token = self._parse_oai_page(content, config)
```

Αυτό επιστρέφει:

- λίστα από parsed records,
- πιθανό `resumptionToken` για την επόμενη page.

Κάθε parsed record είναι dict:

```python
{
    "oai_identifier": "...",
    "datestamp": "...",
    "rdf_xml": "...",
    "dataset": {...}
}
```

Το `dataset` είναι ήδη CKAN package dict από τον DCAT parser.

### Για κάθε record

Για κάθε record:

```python
dataset = record["dataset"]
self._prepare_dataset(dataset, record, source_dataset, harvest_job, config)
```

Η `_prepare_dataset` φροντίζει:

- να υπάρχει `name`,
- να μην υπάρχει duplicate name στο ίδιο gather,
- να μπει `owner_org`,
- να μπει `metadata_modified` από datestamp αν δεν υπάρχει,
- να έχουν resources name.

Μετά υπολογίζεται το harvest guid:

```python
guid = self._record_guid(record, dataset, source_dataset)
```

Το guid είναι το σταθερό κλειδί που δένει ένα remote record με ένα CKAN dataset
σε επόμενα re-harvests.

### Extras που μπαίνουν στο dataset

Ο harvester προσθέτει:

```python
guid
oai_identifier
oai_datestamp
metadata_prefix
```

ως CKAN extras στο dataset. Αυτά βοηθούν στο debugging και στο tracing της
προέλευσης.

### Δημιουργία HarvestObject

```python
obj = HarvestObject(**obj_kwargs)
obj.save()
object_ids.append(obj.id)
```

Το `HarvestObject` περιέχει:

- `guid`,
- σύνδεση με το harvest job,
- `content`: το CKAN dataset dict σε JSON,
- extra `status`: `new` ή `change`,
- αν υπάρχει ήδη package, το `package_id`.

### `resumptionToken`

Αν το OAI-PMH response έχει:

```xml
<resumptionToken>abc123</resumptionToken>
```

τότε ο harvester φτιάχνει επόμενο URL:

```text
?verb=ListRecords&resumptionToken=abc123
```

Σύμφωνα με το OAI-PMH spec, όταν χρησιμοποιείται `resumptionToken`, δεν
ξαναστέλνονται `metadataPrefix`, `set`, `from`, `until`.

Αν υπάρχει:

```json
{"throttle_ms": 500}
```

ο harvester περιμένει 500ms πριν ζητήσει την επόμενη page. Αυτό είναι δικό μας
rate-limiting option, όχι OAI-PMH parameter.

### Deletions

Στο τέλος:

```python
self._mark_datasets_for_deletion(guids_in_source, harvest_job)
```

συγκρίνει:

- τα guids που υπήρχαν από προηγούμενα harvests,
- με τα guids που εμφανίστηκαν τώρα.

Όσα παλιά guids δεν εμφανίστηκαν τώρα, περνούν από τη γενική deletion λογική του
harvester.

## `fetch_stage`

```python
def fetch_stage(self, harvest_object):
    return True
```

Το fetch stage δεν κάνει τίποτα, γιατί το record έχει ήδη γίνει fetch στο
`gather_stage`.

Αυτό είναι διαφορά από το παλιό `/root/ckanext-oaipmh`, όπου:

- gather: έκανε `ListIdentifiers`,
- fetch: έκανε `GetRecord`.

Εδώ:

- gather: κάνει `ListRecords` και παίρνει όλο το metadata.

## `_config`

```python
def _config(self, harvest_job):
```

Διαβάζει το JSON config από το harvest source.

Αν είναι άδειο ή invalid, γυρίζει `{}` και βάζει defaults:

```python
metadata_prefix = "dcat_ap"
rdf_format = "xml"
timeout = 60
```

Αυτό χρησιμοποιείται runtime. Το `validate_config` είναι για έλεγχο κατά την
αποθήκευση του harvest source.

## `_build_oai_url`

```python
def _build_oai_url(self, base_url, config, resumption_token=None):
```

Χτίζει το OAI-PMH request URL.

Χωρίς `resumptionToken`:

```text
?verb=ListRecords&metadataPrefix=dcat_ap
```

Αν υπάρχουν `set`, `from`, `until`, τα προσθέτει:

```text
?verb=ListRecords&metadataPrefix=dcat_ap&set=...&from=...&until=...
```

Με `resumptionToken`:

```text
?verb=ListRecords&resumptionToken=...
```

Δεν προσθέτει άλλα params σε αυτή την περίπτωση, γιατί έτσι ορίζει το OAI-PMH
spec.

## `_load_oai_page`

```python
def _load_oai_page(self, url, harvest_job, config):
```

Φορτώνει μία OAI-PMH page.

Αν το `url` δεν αρχίζει από `http`, το θεωρεί local file path:

```python
with open(url, "rb") as f:
    return f.read()
```

Αν είναι HTTP:

1. φτιάχνει `requests.Session`,
2. βάζει `User-Agent` αν έχει δηλωθεί,
3. βάζει Basic Auth αν υπάρχουν `username` και `password`,
4. κάνει `GET`,
5. κάνει `raise_for_status`,
6. επιστρέφει `response.content`.

Το `response.content` είναι σημαντικό γιατί είναι raw bytes. Δεν χρησιμοποιείται
`response.text`, ώστε να μην κάνει λάθος charset guessing το `requests`.

## `_parse_oai_page`

```python
def _parse_oai_page(self, content, config):
```

Παίρνει το XML μιας OAI-PMH page και επιστρέφει:

```python
(records, resumption_token)
```

### XML parser

```python
parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
```

Οι επιλογές αυτές περιορίζουν external entity/network behavior και κάνουν το
parsing πιο ανθεκτικό.

### OAI-PMH errors

Αν το response περιέχει:

```xml
<error code="...">...</error>
```

τότε σηκώνει `ValueError`, ώστε το gather να γράψει gather error.

### Loop στα records

Ψάχνει:

```python
.//oai:ListRecords/oai:record
```

Για κάθε record:

- βρίσκει το `header`,
- αγνοεί records με `status="deleted"`,
- παίρνει `oai_identifier`,
- παίρνει `datestamp`,
- βρίσκει το πρώτο child του `metadata` που έχει local-name `RDF`.

Χρησιμοποιεί `local-name()='RDF'` για να μην εξαρτάται από το ακριβές namespace
prefix, π.χ. `rdf:RDF`.

Αν δεν υπάρχει RDF metadata, το record αγνοείται.

### RDF parsing

Το RDF element γίνεται string:

```python
rdf_xml = etree.tostring(rdf_elements[0], encoding="unicode")
```

και περνάει στο:

```python
dataset = self._parse_rdf_dataset(rdf_xml, config)
```

Αν δεν προκύψει dataset, το record αγνοείται.

### Token για επόμενη page

Στο τέλος ψάχνει:

```python
.//oai:ListRecords/oai:resumptionToken
```

και το επιστρέφει μαζί με τα records.

## `_parse_rdf_dataset`

```python
def _parse_rdf_dataset(self, rdf_xml, config):
```

Χρησιμοποιεί:

```python
parser = RDFParser()
parser.parse(rdf_xml, _format=config.get("rdf_format") or "xml")
```

Μετά παίρνει το πρώτο dataset από:

```python
parser.datasets()
```

Στο RAISE δείγμα κάθε OAI-PMH record αντιστοιχεί σε ένα DCAT dataset, άρα το
πρώτο dataset είναι αυτό που θέλουμε.

Αν το RDF δεν μπορεί να γίνει parse, επιστρέφει `None` και το record αγνοείται.

## `_prepare_dataset`

```python
def _prepare_dataset(self, dataset, record, source_dataset, harvest_job, config=None):
```

Προετοιμάζει το parsed CKAN package dict πριν αποθηκευτεί στο `HarvestObject`.

Κάνει τα εξής:

1. εξασφαλίζει ότι υπάρχει `extras` list,
2. αν δεν υπάρχει `name`, το φτιάχνει,
3. αποφεύγει duplicate names μέσα στο ίδιο gather,
4. βάζει `owner_org` από το harvest source package,
5. βάζει `metadata_modified` από OAI datestamp αν λείπει,
6. συμπληρώνει resource names αν λείπουν.

## Name generation

Υπάρχουν δύο τρόποι για να φτιαχτεί το CKAN dataset `name`.

### 1. Από DCAT/OAI identifier UUID

Αν στο config υπάρχει:

```json
{
  "dataset_name_prefix_from_identifier": "raise-"
}
```

τότε ο harvester ψάχνει UUID:

1. στο DCAT `identifier`,
2. στο OAI-PMH `header/identifier`,
3. στο DCAT `uri`.

Παράδειγμα:

```text
10.83613/raise-dev/dataset/08dea5d9-7569-4bfd-8563-5c30372a3ef9
```

δίνει:

```text
raise-08dea5d9-7569-4bfd-8563-5c30372a3ef9
```

Αυτό είναι προτεινόμενο για RAISE, γιατί οι ελληνικοί τίτλοι δεν παράγουν καλά
ASCII slugs.

### 2. Από τον τίτλο

Αν δεν υπάρχει `dataset_name_prefix_from_identifier` ή δεν βρεθεί UUID, γίνεται
fallback:

```text
<harvest source name>-<slug from title>
```

Αν δεν υπάρχει harvest source name, χρησιμοποιεί:

```text
oai-pmh
```

Παράδειγμα:

```text
ΗΜΕΡΟΛΟΓΙΟ-ΛΙΑΝΙΚΩΝ-ΤΙΜΩΝ ΚΑΥΣΙΜΩΝ (sample)
```

μπορεί να δώσει slug:

```text
sample
```

άρα name:

```text
oai-pmh-sample
```

Για αυτό προτιμάται το UUID-based naming στο RAISE.

## `_dataset_name_from_identifier_config`

```python
def _dataset_name_from_identifier_config(self, dataset, record, config):
```

Ενεργοποιείται μόνο αν υπάρχει config key:

```json
{
  "dataset_name_prefix_from_identifier": "..."
}
```

Αν δεν υπάρχει, επιστρέφει `None` και η ροή πάει στο title fallback.

Αν υπάρχει:

1. παίρνει πιθανές identifier πηγές,
2. ψάχνει UUID με `_uuid_from_identifier`,
3. αν βρει UUID, καλεί `_dataset_name_from_identifier`.

## `_dataset_name_from_identifier`

```python
def _dataset_name_from_identifier(self, prefix, identifier, config):
```

Ενώνει:

```text
prefix + uuid
```

το κάνει CKAN-safe με `normalize_ckan_name`, και εφαρμόζει `dataset_name_max_length`.

Αν το name είναι μεγαλύτερο από το όριο, κόβει το string και προσθέτει σταθερό
hash suffix. Αυτό κρατά το name deterministic για re-harvests.

## `_dataset_name_max_length`

```python
def _dataset_name_max_length(self, config):
```

Διαβάζει:

```json
{
  "dataset_name_max_length": 100
}
```

Αν λείπει ή δεν είναι σωστό, χρησιμοποιεί default `100`.

## `_dataset_identifier`

```python
def _dataset_identifier(self, dataset):
```

Ψάχνει identifier μέσα στο parsed dataset:

1. top-level `dataset["identifier"]`,
2. extra με `key == "identifier"`,
3. top-level `dataset["uri"]`,
4. extra με `key == "uri"`.

Στο RAISE fixture το `identifier` έρχεται ως extra:

```python
{"key": "identifier", "value": "10.83613/raise-dev/dataset/..."}
```

## `_uuid_from_identifier`

```python
def _uuid_from_identifier(self, identifier):
```

Παίρνει ένα string και επιστρέφει το πρώτο UUID που βρίσκει.

Αν δεν βρει UUID, επιστρέφει `None`.

## `_dataset_name_from_title`

```python
def _dataset_name_from_title(self, dataset, source_dataset):
```

Είναι το fallback name generation.

Παίρνει τον καλύτερο διαθέσιμο τίτλο με `_best_title`, τον περνά από
`_gen_new_name`, και προσθέτει prefix από το harvest source package name.

Αυτή η λογική μοιάζει με τους υπάρχοντες DCAT harvesters, αλλά για ελληνικούς
τίτλους μπορεί να δώσει φτωχό slug αν ο τίτλος δεν περιέχει λατινικούς
χαρακτήρες.

## `_ensure_resource_names`

```python
def _ensure_resource_names(self, dataset):
```

Αν το DCAT parser φέρει resources χωρίς `name`, ο harvester βάζει fallback:

- αν υπάρχει ένας resource: παίρνει το dataset title,
- αν υπάρχουν πολλοί: παίρνουν `<dataset title> - resource <n>`.

Αυτό βοηθά κυρίως πηγές όπως το RAISE, όπου το distribution έχει access URL αλλά
όχι πάντα δικό του title/name.

## `_best_title`

```python
def _best_title(self, dataset):
```

Βρίσκει τον καλύτερο διαθέσιμο τίτλο:

1. `dataset["title"]`,
2. `title_translated["el"]`,
3. `title_translated["en"]`,
4. `identifier`,
5. `uri`,
6. `"Untitled Dataset"`.

Χρησιμοποιείται για:

- fallback dataset name,
- fallback resource names.

## `_record_guid`

```python
def _record_guid(self, record, dataset, source_dataset):
```

Υπολογίζει το harvest guid.

Πρώτα χρησιμοποιεί τη `_get_guid` του DCAT harvester, που κοιτάει τα DCAT fields
του dataset. Αν δεν βρει κάτι, κάνει fallback στο OAI-PMH `header/identifier`.

Το guid είναι κρίσιμο γιατί με αυτό γίνεται η αντιστοίχιση:

```text
remote record <-> CKAN package
```

σε κάθε re-harvest.

## `_append_unique_extra`

```python
def _append_unique_extra(self, dataset, key, value):
```

Προσθέτει extra στο dataset μόνο αν:

- το value δεν είναι `None`,
- δεν υπάρχει ήδη extra με το ίδιο key.

Χρησιμοποιείται για να προστεθούν:

- `guid`,
- `oai_identifier`,
- `oai_datestamp`,
- `metadata_prefix`.

## `_extra_value`

```python
def _extra_value(self, dataset, key):
```

Διαβάζει από `dataset["extras"]` την πρώτη τιμή με συγκεκριμένο key.

Χρησιμοποιείται κυρίως επειδή ο `RDFParser` βάζει κάποια DCAT πεδία ως extras
και όχι ως top-level fields.

## `_existing_guid_to_package_id`

```python
def _existing_guid_to_package_id(self, harvest_job):
```

Κάνει query στα current `HarvestObject` της ίδιας harvest source και γυρίζει map:

```python
{
  guid: package_id
}
```

Αυτό χρησιμοποιείται στο gather για να αποφασιστεί αν ένα record είναι:

- `new`: δεν υπήρχε πριν,
- `change`: υπήρχε ήδη και πρέπει να ενημερωθεί.

## `_first_text`

```python
def _first_text(self, element, xpath):
```

Μικρό XML helper.

Τρέχει XPath με το OAI namespace και επιστρέφει το text του πρώτου match.

Χρησιμοποιείται για:

- `header/identifier`,
- `header/datestamp`,
- `resumptionToken`.

## Configuration reference

### `metadata_prefix`

Προαιρετικό string. Default: `dcat_ap`.

OAI-PMH parameter. Μπαίνει στο αρχικό request:

```text
verb=ListRecords&metadataPrefix=dcat_ap
```

### `rdf_format`

Προαιρετικό string. Default: `xml`.

Δεν είναι OAI-PMH parameter. Είναι format για τον `ckanext-dcat` `RDFParser`.
Για DCAT-AP RDF/XML θέλουμε:

```json
{"rdf_format": "xml"}
```

### `set`

Προαιρετικό string.

OAI-PMH parameter. Μπαίνει μόνο αν το δηλώσεις:

```text
verb=ListRecords&metadataPrefix=dcat_ap&set=<setSpec>
```

Δεν είναι γενικό. Πρέπει το endpoint να έχει τέτοιο `setSpec`, το οποίο φαίνεται
με:

```text
?verb=ListSets
```

### `from` / `until`

Προαιρετικά strings.

OAI-PMH parameters για selective harvesting βάσει datestamp:

```text
verb=ListRecords&metadataPrefix=dcat_ap&from=2026-01-01&until=2026-01-31
```

Είναι μέρος του OAI-PMH spec, αλλά δεν υπήρχαν ως υλοποίηση στο παλιό
`ckanext-oaipmh`.

### `dataset_name_prefix_from_identifier`

Προαιρετικό string.

Δεν είναι OAI-PMH parameter. Είναι δική μας επιλογή για CKAN dataset naming.

Παράδειγμα:

```json
{"dataset_name_prefix_from_identifier": "raise-"}
```

### `dataset_name_max_length`

Προαιρετικός ακέραιος. Default: `100`.

Δεν είναι OAI-PMH parameter. Είναι δική μας επιλογή για CKAN-safe dataset names.

### `timeout`

Προαιρετικός ακέραιος. Default: `60`.

Δεν είναι OAI-PMH parameter. Είναι timeout του HTTP request.

### `user_agent`

Προαιρετικό string.

Δεν είναι OAI-PMH parameter. Μπαίνει ως HTTP `User-Agent` header.

### `username` / `password`

Προαιρετικά strings.

Δεν είναι OAI-PMH parameters. Χρησιμοποιούνται ως HTTP Basic Auth credentials.
Αυτή η ιδέα υπήρχε και στο παλιό `/root/ckanext-oaipmh`.

### `max_pages`

Προαιρετικός ακέραιος.

Δεν είναι OAI-PMH parameter. Είναι δική μας επιλογή για testing/debugging.

Περιορίζει πόσες OAI-PMH pages θα διαβάσει ο harvester. Χρήσιμο αν ένα endpoint
έχει πολλά records και θέλουμε να δοκιμάσουμε μόνο την πρώτη page.

### `throttle_ms`

Προαιρετικός ακέραιος.

Δεν είναι OAI-PMH parameter. Είναι δική μας επιλογή για rate limiting.

Αν υπάρχει `resumptionToken`, ο harvester περιμένει τόσα milliseconds πριν
ζητήσει την επόμενη page.

## Τι αποθηκεύεται στο HarvestObject

Για κάθε OAI-PMH record δημιουργείται `HarvestObject` με:

```python
guid = <stable harvest guid>
job = <τρέχον harvest job>
content = json.dumps(dataset)
extras = [HarvestObjectExtra(key="status", value="new" ή "change")]
package_id = <existing package id, αν υπάρχει>
```

Το `content` είναι το CKAN package dict που ήρθε από τον DCAT parser και πέρασε
από την προετοιμασία του harvester.

Παράλληλα, μέσα στο dataset extras μπαίνουν:

```text
guid
oai_identifier
oai_datestamp
metadata_prefix
```

## Τι συμβαίνει με τα resources

Το resource mapping έρχεται κυρίως από τον `ckanext-dcat` parser.

Στο RAISE δείγμα βλέπουμε συνήθως:

```xml
<dcat:Distribution>
  <dcat:accessURL rdf:resource="https://develop.portal.raise-science.eu/datasets/..."/>
  <dct:format rdf:resource="http://publications.europa.eu/resource/authority/file-type/CSV"/>
  <dcat:byteSize>0</dcat:byteSize>
  <dct:license rdf:resource="..."/>
</dcat:Distribution>
```

Αυτό δίνει CKAN resource με:

- `url`,
- `access_url`,
- `format`,
- πιθανό `size`,
- πιθανή license πληροφορία.

Αν δεν υπάρχει `dcat:downloadURL`, δεν έχουμε απευθείας download file. Το CKAN
resource δείχνει στη σελίδα πρόσβασης του RAISE dataset.

## Τι πρέπει να προσέχουμε

- Το harvest source URL πρέπει να είναι base OAI-PMH endpoint, όχι URL με ήδη
  κολλημένο `verb=ListRecords`.
- Το `set` μπαίνει μόνο αν το endpoint το υποστηρίζει.
- Το `from` / `until` μπαίνουν μόνο όταν θέλουμε selective harvesting.
- Το `dataset_name_prefix_from_identifier` είναι προτεινόμενο για RAISE.
- Το `response.content` / binary file read είναι σημαντικό για σωστό UTF-8.
- Το `fetch_stage` είναι intentionally no-op.
- Το πραγματικό create/update γίνεται από inherited DCAT import flow.

## Χρήσιμο RAISE config

```json
{
  "metadata_prefix": "dcat_ap",
  "rdf_format": "xml",
  "dataset_name_prefix_from_identifier": "raise-",
  "dataset_name_max_length": 100,
  "timeout": 60,
  "user_agent": "data.gov.gr OAI-PMH DCAT Harvester"
}
```

Με harvest source URL:

```text
https://develop.api.portal.raise-science.eu/oai/user/0f868393-e7b7-49c2-9a2b-5421b6fbd266
```

Για γρήγορη δοκιμή μόνο στην πρώτη OAI-PMH page:

```json
{
  "metadata_prefix": "dcat_ap",
  "rdf_format": "xml",
  "dataset_name_prefix_from_identifier": "raise-",
  "max_pages": 1
}
```
