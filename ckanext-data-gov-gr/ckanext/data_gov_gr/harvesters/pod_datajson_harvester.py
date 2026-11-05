# -*- coding: utf-8 -*-
"""
Γενικός harvester για καταλόγους POD / DCAT-US (``data.json``).

Το POD (Project Open Data) ``data.json`` είναι JSON-LD και διαβάζεται από τον
CustomDcatHarvester. Το JSON-LD context του POD όμως δεν ταιριάζει πλήρως με
το DCAT-AP (π.χ. ``name`` -> ``skos:prefLabel``, ``hasEmail`` -> ``vcard:email``,
``license`` ως απλό κείμενο), οπότε ορισμένα πεδία χάνονται. Ο harvester αυτός
ξαναδιαβάζει την αντίστοιχη εγγραφή του ``data.json`` και συμπληρώνει:

  - publisher (όνομα) και email επικοινωνίας,
  - άδεια, θεματική κατηγορία (theme) και κατηγορία HVD, μέσω αντιστοιχίσεων,
  - απόλυτα URLs για εικόνες με σχετικό ``src`` στην περιγραφή.

Διαμόρφωση πηγής (JSON στο πεδίο «Διαμόρφωση» του UI). Όλα τα κλειδιά είναι
προαιρετικά. Ο γενικός harvester δεν έχει ενσωματωμένες αντιστοιχίσεις
(άδειες, θέματα, HVD): ό,τι δεν δηλωθεί δεν αντιστοιχίζεται. Υποκλάσεις
(π.χ. ApdKritisHarvester) μπορούν να έχουν δικές τους προεπιλογές.

  - ``rdf_format``: προεπιλογή ``"json-ld"``.
  - ``dataset_name_prefix``: (CustomDcatHarvester) όνομα = ``<prefix>-<identifier>``.
  - ``license_map``: ``{"<άδεια στην πηγή>": "<κωδικός EU ή URI>"}``,
    π.χ. ``{"https://creativecommons.org/licenses/by/4.0/": "CC_BY_4_0"}``.
    Τα URL συγκρίνονται χωρίς διάκριση http/https και τελικού ``/``. Άδειες
    χωρίς αντιστοίχιση, ή με τιμή που δεν υπάρχει στο λεξιλόγιο «Licence»,
    μένουν κενές.
  - ``theme_map``: ``{"<theme στην πηγή>": "<κωδικός EU Data Theme ή URI>"}``,
    π.χ. ``{"Περιβάλλον": "ENVI"}``. Δέχεται και λίστα τιμών. Τα theme της
    πηγής συγκρίνονται χωρίς διάκριση πεζών/κεφαλαίων.
  - ``hvd_keyword``: λέξη-κλειδί που χαρακτηρίζει ένα dataset ως High Value
    (προεπιλογή ``"High Value Dataset"``).
  - ``hvd_category_map``: ``{"<theme στην πηγή>": "<URI κατηγορίας HVD>"}``.
  - ``relative_url_base``: domain για σχετικά ``src`` εικόνων στην περιγραφή
    (προεπιλογή: το domain του URL της πηγής). Κρατιέται μόνο το
    ``scheme://host``, γιατί τα ``src="/..."`` είναι σχετικά με τη ρίζα.
  - ``skip_publisher``: ``true`` για να μη γράφεται publisher.
  - ``user_agent``: (CustomDcatHarvester) User-Agent για τα αιτήματα, και για
    το data.json που κατεβαίνει στο import.
  - ``default_dataset_fields`` / ``default_resource_fields`` (και τα αντίστοιχα
    ``override_*``): προεπιλεγμένες τιμές πεδίων (harvest_mapping). Οι τιμές
    γράφονται όπως είναι, χωρίς μετατροπή· π.χ. για άδεια στα resources
    χρειάζεται ολόκληρο URI
    (``http://publications.europa.eu/resource/authority/licence/CC_BY_4_0``).
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .custom_dcat_harvester import CustomDcatHarvester, harvest_local
from ..logic.harvest_mapping import (
    apply_default_resource_fields_from_config,
    get_harvest_source_config,
)

log = logging.getLogger(__name__)

# Cache του ευρετηρίου του data.json ανά URL. Κρατάμε μόνο το τελευταίο job ανά
# URL, ώστε κάθε νέο harvest job να ξανακατεβάζει τον κατάλογο (όχι μόνιμα παλιά
# δεδομένα). Το None σημαίνει ότι το κατέβασμα απέτυχε σε αυτό το job.
# Μορφή: {catalog_url: (job_id, {identifier: εγγραφή} ή None)}
_pod_catalog_cache: Dict[str, Tuple[Optional[str], Optional[Dict[str, Any]]]] = {}

# Cache των λεξιλογίων (κωδικός -> τιμή) ανά harvest job: {όνομα: (job_id, map)}
_vocabulary_uri_cache: Dict[str, Tuple[Optional[str], Dict[str, str]]] = {}

# src="/..." ή src='/...' (σχετικό URL), αλλά όχι src="//..." (χωρίς πρωτόκολλο)
_RELATIVE_SRC_RE = re.compile(r"""(src=["'])/(?!/)""")

_DATA_THEME_BASE_URI = "http://publications.europa.eu/resource/authority/data-theme/"
_HVD_CATEGORY_BASE_URI = "http://data.europa.eu/bna/"

# Κλειδιά διαμόρφωσης που ελέγχονται στο validate_config
_MAP_CONFIG_KEYS = ("license_map", "theme_map", "hvd_category_map")
_BOOLEAN_CONFIG_KEYS = (
    "skip_publisher",
    "override_default_dataset_fields",
    "override_default_resource_fields",
)


def _normalize_license_key(value: str) -> str:
    """
    Κλειδί σύγκρισης για άδειες: χωρίς κενά, πεζά, χωρίς τελικό "/" και
    χωρίς διάκριση http/https (το ίδιο URL γράφεται με διάφορους τρόπους).
    """
    key = value.strip().lower().rstrip("/")
    if key.startswith("http://"):
        key = "https://" + key[len("http://"):]
    return key


class PodDataJsonHarvester(CustomDcatHarvester):
    """
    Γενικός, παραμετροποιήσιμος harvester για POD / DCAT-US ``data.json``.

    Οι υποκλάσεις (π.χ. ApdKritisHarvester) μπορούν να ορίσουν δικές τους
    προεπιλογές μέσω των class attributes ``DEFAULT_*``· η διαμόρφωση της
    πηγής έχει πάντα προτεραιότητα.
    """

    # Πρόθεμα στα μηνύματα του log
    LOG_PREFIX = "[POD DATAJSON HARVESTER]"

    # Άδεια στην πηγή (lowercase) -> τιμή που κανονικοποιεί ο CustomDcatHarvester
    # (_fix_license_field) σε EU authority URI. Κενό: οι αντιστοιχίσεις δηλώνονται
    # στο license_map της διαμόρφωσης κάθε πηγής.
    DEFAULT_LICENSE_MAP: Dict[str, str] = {}

    # Theme στην πηγή -> EU Data Theme (κωδικός ή URI). Κενό: καμία αντιστοίχιση.
    DEFAULT_THEME_MAP: Dict[str, Any] = {}

    # Theme στην πηγή -> URI κατηγορίας HVD. Κενό: καμία αντιστοίχιση.
    DEFAULT_HVD_CATEGORY_MAP: Dict[str, Any] = {}

    DEFAULT_HVD_KEYWORD = "High Value Dataset"

    # None: παράγεται από το domain του URL της πηγής
    DEFAULT_RELATIVE_URL_BASE: Optional[str] = None

    # Διαδρομή που προστίθεται όταν το URL της πηγής δεν τελειώνει σε data.json.
    # None: χρησιμοποιείται το URL της πηγής όπως είναι (το ίδιο που κατέβασε
    # το gather stage).
    DEFAULT_CATALOG_PATH: Optional[str] = None

    def __new__(cls, *args, **kwargs):
        # Το SingletonPlugin του CKAN ελέγχει hasattr(cls, "_instance"), που βρίσκει
        # και το _instance της γονικής κλάσης: αν η γονική φορτωθεί πρώτη στο
        # ckan.plugins, η υποκλάση παίρνει το αντικείμενο της γονικής. Εδώ κάθε
        # κλάση (αυτή και οι υποκλάσεις της) κρατά το δικό της singleton,
        # ανεξάρτητα από τη σειρά των plugins.
        if "_instance" not in cls.__dict__:
            cls._instance = object.__new__(cls)
        return cls._instance

    def info(self):
        return {
            "name": "pod_datajson_harvester",
            "title": "POD data.json Harvester",
            "description": (
                "Γενικός harvester για καταλόγους POD (data.json). "
                "Αντιστοιχίσεις αδειών, θεμάτων και HVD ορίζονται στη "
                "διαμόρφωση της πηγής."
            ),
            "form_config_interface": "Text",
            "show_config": True,
        }

    # ------------------------------------------------------------------
    # Διαμόρφωση
    # ------------------------------------------------------------------

    def validate_config(self, source_config: Optional[str]):
        """
        Ελέγχει τη διαμόρφωση της πηγής και βάζει ``rdf_format: json-ld``
        όταν λείπει (το POD data.json είναι JSON-LD).
        """
        if not source_config:
            return json.dumps({"rdf_format": "json-ld"})

        try:
            conf = json.loads(source_config)
        except ValueError:
            # Ίδιος χειρισμός σφάλματος με τη βασική κλάση
            return super().validate_config(source_config)

        # Και τα "κενά" JSON (π.χ. [], 0, false) απορρίπτονται: μόνο αντικείμενο
        if not isinstance(conf, dict):
            raise ValueError("Η διαμόρφωση πρέπει να είναι JSON αντικείμενο")

        for key in _BOOLEAN_CONFIG_KEYS:
            if key in conf and not isinstance(conf[key], bool):
                raise ValueError(f"Το {key} πρέπει να είναι true ή false (χωρίς εισαγωγικά)")

        if not conf.get("rdf_format"):
            conf["rdf_format"] = "json-ld"

        for key in _MAP_CONFIG_KEYS:
            if key not in conf:
                continue
            mapping = conf[key]
            if not isinstance(mapping, dict):
                raise ValueError(f"Το {key} πρέπει να είναι αντικείμενο {{\"τιμή πηγής\": \"τιμή\"}}")
            for source_value, target in mapping.items():
                valid_target = isinstance(target, str) or (
                    isinstance(target, list) and all(isinstance(t, str) for t in target)
                )
                if not isinstance(source_value, str) or not valid_target:
                    raise ValueError(f"Μη έγκυρη εγγραφή στο {key}: {source_value!r}")
            if key == "license_map" and any(not isinstance(t, str) for t in mapping.values()):
                raise ValueError("Στο license_map κάθε τιμή πρέπει να είναι μία άδεια (κείμενο)")

        if "hvd_keyword" in conf and not isinstance(conf["hvd_keyword"], str):
            raise ValueError("Το hvd_keyword πρέπει να είναι κείμενο")

        if "relative_url_base" in conf:
            base = conf["relative_url_base"]
            if not isinstance(base, str) or not base.strip().lower().startswith(("http://", "https://")):
                raise ValueError("Το relative_url_base πρέπει να είναι URL (http:// ή https://)")

        for key in ("default_dataset_fields", "default_resource_fields"):
            if key in conf and not isinstance(conf[key], dict):
                raise ValueError(f"Το {key} πρέπει να είναι αντικείμενο")

        return super().validate_config(json.dumps(conf, ensure_ascii=False))

    def _get_license_map(self, config: Dict[str, Any]) -> Dict[str, str]:
        mapping = {_normalize_license_key(k): v for k, v in self.DEFAULT_LICENSE_MAP.items()}
        custom = config.get("license_map")
        if isinstance(custom, dict):
            for key, value in custom.items():
                if isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip():
                    mapping[_normalize_license_key(key)] = value.strip()
        return mapping

    def _get_theme_map(self, config: Dict[str, Any], key: str, defaults: Dict[str, Any]) -> Dict[str, List[str]]:
        # Κλειδιά χωρίς διάκριση πεζών/κεφαλαίων (casefold), όπως και στις άδειες
        mapping: Dict[str, List[str]] = {}
        for source in (defaults, config.get(key)):
            if not isinstance(source, dict):
                continue
            for label, value in source.items():
                if not isinstance(label, str) or not label.strip():
                    continue
                values = value if isinstance(value, list) else [value]
                values = [v.strip() for v in values if isinstance(v, str) and v.strip()]
                if values:
                    mapping[label.strip().casefold()] = values
        return mapping

    def _get_relative_url_base(self, config: Dict[str, Any], harvest_object) -> Optional[str]:
        # Μόνο scheme://host: τα src="/..." είναι σχετικά με τη ρίζα του site
        base = config.get("relative_url_base") or self.DEFAULT_RELATIVE_URL_BASE
        if not (isinstance(base, str) and base.strip()):
            base = self._get_source_url(harvest_object)

        parsed = urlparse((base or "").strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return None

    # ------------------------------------------------------------------
    # Κύρια ροή
    # ------------------------------------------------------------------

    def modify_package_dict(self, package_dict, temp_dict, harvest_object):
        """
        Πριν τη βασική κλάση: άδεια από το data.json (ώστε να κανονικοποιηθεί
        και να περάσει στα resources). Μετά: conformsTo, HVD, theme, επαφή,
        publisher, σχετικά URLs εικόνων και default_resource_fields.
        """
        config = get_harvest_source_config(harvest_object)
        self._current_job_id = getattr(getattr(harvest_object, "job", None), "id", None)

        source_dataset = None
        try:
            source_dataset = self._get_pod_source_dataset(harvest_object)
        except Exception as e:
            log.error("%s Error loading POD source dataset: %s", self.LOG_PREFIX, e, exc_info=True)

        try:
            if source_dataset:
                self._inject_license_from_source(package_dict, source_dataset, config)
        except Exception as e:
            log.error("%s Error applying licence mapping: %s", self.LOG_PREFIX, e, exc_info=True)

        package_dict = super().modify_package_dict(package_dict, temp_dict, harvest_object)

        # Κάθε βήμα τρέχει μόνο του, ώστε ένα σφάλμα να μη σταματά τα επόμενα
        if config.get("skip_publisher"):
            package_dict.pop("publisher", None)

        if source_dataset:
            self._run_step("conformsTo", self._drop_empty_conforms_to_from_source, package_dict, source_dataset)
            self._run_step("HVD", self._apply_hvd_category_from_source, package_dict, source_dataset, config)
            self._run_step("theme", self._apply_data_theme_from_source, package_dict, source_dataset, config)
            self._run_step("contact", self._fix_contact_from_source, package_dict, source_dataset)
            if not config.get("skip_publisher"):
                self._run_step("publisher", self._fix_publisher_from_source, package_dict, source_dataset)

        self._run_step(
            "relative URLs", self._fix_relative_urls_in_description, package_dict, config, harvest_object
        )
        self._run_step(
            "default_resource_fields", apply_default_resource_fields_from_config, package_dict, harvest_object
        )

        return package_dict

    def _run_step(self, name, func, *args) -> None:
        try:
            func(*args)
        except Exception as e:
            log.error("%s Error in step '%s': %s", self.LOG_PREFIX, name, e, exc_info=True)

    # ------------------------------------------------------------------
    # POD data.json
    # ------------------------------------------------------------------

    def _get_source_url(self, harvest_object) -> Optional[str]:
        # Ίδια σειρά με το get_harvest_source_config, ώστε URL και config να
        # προέρχονται πάντα από την ίδια πηγή
        for path in (("source",), ("job", "source")):
            current = harvest_object
            for attr in path:
                current = getattr(current, attr, None) if current is not None else None
            url = getattr(current, "url", None) if current is not None else None
            if isinstance(url, str) and url.strip():
                return url.strip()
        return None

    def _get_pod_source_dataset(self, harvest_object) -> Optional[Dict[str, Any]]:
        """
        Βρίσκει στο data.json την εγγραφή που αντιστοιχεί στο harvest object,
        με βάση το guid (URI ή dcat:identifier), συγκρίνοντας με τα
        identifier / id / @id της εγγραφής.
        """
        if not harvest_object:
            return None

        guid = getattr(harvest_object, "guid", None)
        job = getattr(harvest_object, "job", None)
        source_url = self._get_source_url(harvest_object)

        if not guid or not source_url:
            return None

        index, catalog_url = self._get_pod_index(source_url, job)
        if not index:
            return None

        guid = str(guid).strip()

        # 1. Ακριβές ταίριασμα με identifier / id / @id
        candidate = index.get(guid)
        if candidate is not None:
            log.debug("%s Matched POD dataset %s in %s", self.LOG_PREFIX, guid, catalog_url)
            return candidate

        # 2. Σχετικό @id (π.χ. "abc") που το rdflib έκανε URI του τρέχοντος
        #    φακέλου (file:///.../abc): ψάχνουμε το τελευταίο τμήμα του guid
        if "/" in guid:
            tail = guid.rstrip("/").rsplit("/", 1)[-1]
            candidate = index.get(tail) if tail else None
            if candidate is not None:
                log.debug("%s Matched POD dataset %s by last URI segment in %s", self.LOG_PREFIX, guid, catalog_url)
                return candidate

        log.warning("%s No matching POD dataset for guid=%s in %s", self.LOG_PREFIX, guid, catalog_url)
        return None

    def _get_catalog_url(self, source_url: str) -> Optional[str]:
        url = (source_url or "").strip()
        if not url:
            return None
        # Γενικός harvester: το URL της πηγής όπως είναι (το ίδιο με το gather)
        if not self.DEFAULT_CATALOG_PATH:
            return url
        base = url.rstrip("/")
        if base.endswith("data.json"):
            return base
        return base + self.DEFAULT_CATALOG_PATH

    def _get_pod_index(self, source_url: str, harvest_job) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Επιστρέφει ευρετήριο ``{identifier / id / @id: εγγραφή}`` του data.json
        της πηγής.

        Ο κατάλογος κατεβαίνει μία φορά ανά harvest job. Και η αποτυχία
        (κατέβασμα ή χαλασμένο αρχείο) κρατιέται για όλο το job, ώστε να μη
        γίνεται νέο αίτημα (και νέο σφάλμα στο job) για κάθε dataset.
        """
        catalog_url = self._get_catalog_url(source_url)
        if not catalog_url:
            return None, None

        job_id = getattr(harvest_job, "id", None)
        cached = _pod_catalog_cache.get(catalog_url)
        if cached and cached[0] == job_id:
            return cached[1], catalog_url

        index = None
        try:
            catalog = self._fetch_pod_catalog(catalog_url, harvest_job)
            if catalog is not None:
                index = self._build_pod_index(catalog, catalog_url)
        except Exception as e:
            log.error("%s Error indexing POD catalog %s: %s", self.LOG_PREFIX, catalog_url, e, exc_info=True)
            index = None

        _pod_catalog_cache[catalog_url] = (job_id, index)
        return index, catalog_url

    def _fetch_pod_catalog(self, catalog_url: str, harvest_job) -> Optional[Dict[str, Any]]:
        # Το import τρέχει σε άλλο process (fetch consumer) από το gather, οπότε
        # το user_agent της πηγής ορίζεται ξανά εδώ (όπως στο gather_stage)
        user_agent = get_harvest_source_config(harvest_job).get("user_agent")
        harvest_local.user_agent = user_agent if isinstance(user_agent, str) and user_agent.strip() else None

        try:
            # Ίδιος HTTP helper με τον DCATRDFHarvester (proxies, user agent κλπ)
            content, _ = self._get_content_and_type(
                catalog_url, harvest_job, page=1, content_type="application/json"
            )
        except Exception as e:
            log.error("%s Error fetching POD catalog %s: %s", self.LOG_PREFIX, catalog_url, e, exc_info=True)
            return None

        if not content:
            log.warning("%s Empty content returned for POD catalog %s", self.LOG_PREFIX, catalog_url)
            return None

        try:
            data = json.loads(content)
        except ValueError as e:
            log.error("%s Error parsing POD catalog JSON from %s: %s", self.LOG_PREFIX, catalog_url, e, exc_info=True)
            return None

        if not isinstance(data, dict):
            log.warning("%s POD catalog %s is not a JSON object, got %r", self.LOG_PREFIX, catalog_url, type(data))
            return None

        return data

    def _build_pod_index(self, catalog: Dict[str, Any], catalog_url: str = "") -> Dict[str, Dict[str, Any]]:
        datasets = catalog.get("dataset") or []
        if not isinstance(datasets, list):
            raise ValueError(f"'dataset' is not a list (got {type(datasets).__name__})")

        index: Dict[str, Any] = {}
        ambiguous = set()

        for candidate in datasets:
            if not isinstance(candidate, dict):
                continue

            values = set()
            for key in ("identifier", "id", "@id"):
                raw = candidate.get(key)
                raw_values = raw if isinstance(raw, list) else [raw]
                values.update(str(v).strip() for v in raw_values if v is not None and str(v).strip())

            for value in values:
                if value in index and index[value] is not candidate:
                    ambiguous.add(value)
                else:
                    index[value] = candidate

        # Ίδιο identifier σε περισσότερες εγγραφές: δεν διαλέγουμε καμία, για να
        # μην πάρει ένα dataset άδεια/θέμα/επαφή από άλλο
        for value in ambiguous:
            index.pop(value, None)
        if ambiguous:
            log.warning(
                "%s %d identifiers appear in more than one dataset of %s and are ignored: %s",
                self.LOG_PREFIX,
                len(ambiguous),
                catalog_url,
                sorted(ambiguous)[:10],
            )

        return index

    # ------------------------------------------------------------------
    # Άδεια
    # ------------------------------------------------------------------

    def _inject_license_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
        config: Dict[str, Any],
    ) -> None:
        """
        Διαβάζει την άδεια της εγγραφής του data.json και, αν υπάρχει
        αντιστοίχιση στο license_map, τη γράφει στο ``license`` ώστε η βασική
        κλάση να την κανονικοποιήσει σε EU URI και να την περάσει στα resources.
        Δεν αλλάζει άδεια που υπάρχει ήδη.
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        license_value = source_dataset.get("license") or source_dataset.get("license_id")
        if not isinstance(license_value, str) or not license_value.strip():
            return

        mapped = self._get_license_map(config).get(_normalize_license_key(license_value))
        if not mapped:
            log.debug("%s No licence mapping for %r; leaving licence empty", self.LOG_PREFIX, license_value)
            return

        if package_dict.get("license") or package_dict.get("license_id"):
            return

        # Έλεγχος με την ίδια κανονικοποίηση που κάνει η βασική κλάση
        # (_fix_license_field): δέχεται κωδικούς EU, URIs και τα γνωστά
        # ψευδώνυμα (π.χ. "cc-by"). Τιμή εκτός λεξιλογίου «Licence» αγνοείται.
        probe = {"license": mapped}
        self._fix_license_field(probe)
        resolved = probe.get("license")
        if not resolved:
            self._warn_once(
                ("license_map", mapped),
                "%s Value %r in license_map not found in vocabulary 'Licence'; skipped",
                self.LOG_PREFIX,
                mapped,
            )
            return

        package_dict["license"] = resolved
        log.debug("%s Injected dataset-level licence %r for downstream normalisation", self.LOG_PREFIX, resolved)

    def _warn_once(self, key, message, *args) -> None:
        # Ένα warning ανά harvest job για την ίδια λάθος τιμή του config
        job_id = getattr(self, "_current_job_id", None)
        if getattr(self, "_warned_job_id", object()) != job_id:
            self._warned_job_id = job_id
            self._warned_keys = set()
        if key in self._warned_keys:
            return
        self._warned_keys.add(key)
        log.warning(message, *args)

    # ------------------------------------------------------------------
    # Theme / HVD
    # ------------------------------------------------------------------

    def _source_list(self, source_dataset: Dict[str, Any], key: str) -> List[str]:
        value = source_dataset.get(key) or []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if v is not None and str(v).strip()]

    def _get_cached_vocabulary_uri_map(self, vocabulary_name: str) -> Dict[str, str]:
        # Το λεξιλόγιο φορτώνεται μία φορά ανά harvest job
        job_id = getattr(self, "_current_job_id", None)
        cached = _vocabulary_uri_cache.get(vocabulary_name)
        if cached and cached[0] == job_id:
            return cached[1]
        uri_map = self._get_vocabulary_uri_map(vocabulary_name) or {}
        _vocabulary_uri_cache[vocabulary_name] = (job_id, uri_map)
        return uri_map

    def _resolve_vocabulary_value(
        self,
        value: str,
        vocabulary_name: str,
        base_uri: str,
        map_name: str,
        upper_code: bool,
    ) -> Optional[str]:
        """
        Μετατρέπει μια τιμή του map (κωδικό ή URI) στην ακριβή τιμή του
        λεξιλογίου. Τιμές που δεν υπάρχουν στο λεξιλόγιο αγνοούνται (με
        μήνυμα στο log), ώστε να μην αποτυγχάνει το validation του dataset.
        """
        is_uri = value.lower().startswith(("http://", "https://"))
        uri_map = self._get_cached_vocabulary_uri_map(vocabulary_name)

        if not uri_map:
            # Το λεξιλόγιο δεν φορτώθηκε: URI όπως είναι, κωδικός -> URI
            code = value.upper() if upper_code else value
            return value if is_uri else f"{base_uri}{code}"

        if is_uri:
            wanted = value.rstrip("/").lower()
            for canonical in uri_map.values():
                if isinstance(canonical, str) and canonical.rstrip("/").lower() == wanted:
                    return canonical
        else:
            canonical = uri_map.get(value.upper())
            if canonical:
                return canonical

        self._warn_once(
            (map_name, value),
            "%s Value %r in %s not found in vocabulary '%s'; skipped",
            self.LOG_PREFIX,
            value,
            map_name,
            vocabulary_name,
        )
        return None

    def _apply_data_theme_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
        config: Dict[str, Any],
    ) -> None:
        """
        Αντιστοιχίζει τα ``theme`` της εγγραφής του data.json σε EU Data Theme
        URIs, σύμφωνα με το theme_map.
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        theme_map = self._get_theme_map(config, "theme_map", self.DEFAULT_THEME_MAP)
        if not theme_map:
            return

        uris: List[str] = []
        for theme in self._source_list(source_dataset, "theme"):
            for value in theme_map.get(theme.casefold(), []):
                uri = self._resolve_vocabulary_value(
                    value, "Data theme", _DATA_THEME_BASE_URI, "theme_map", upper_code=True
                )
                if uri and uri not in uris:
                    uris.append(uri)

        if not uris:
            return

        package_dict["theme"] = uris
        log.debug("%s Applied data theme(s)=%r based on POD theme labels", self.LOG_PREFIX, uris)

    def _apply_hvd_category_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
        config: Dict[str, Any],
    ) -> None:
        """
        Όταν η εγγραφή έχει τη λέξη-κλειδί HVD (hvd_keyword), βάζει
        ``hvd_category`` από τα theme της, σύμφωνα με το hvd_category_map.
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        hvd_map = self._get_theme_map(config, "hvd_category_map", self.DEFAULT_HVD_CATEGORY_MAP)
        if not hvd_map:
            return

        keyword = config.get("hvd_keyword") or self.DEFAULT_HVD_KEYWORD
        if not isinstance(keyword, str) or not keyword.strip():
            return
        keyword = keyword.strip().casefold()

        if not any(k.casefold() == keyword for k in self._source_list(source_dataset, "keyword")):
            return

        uris: List[str] = []
        for theme in self._source_list(source_dataset, "theme"):
            for value in hvd_map.get(theme.casefold(), []):
                uri = self._resolve_vocabulary_value(
                    value,
                    "High-value dataset categories",
                    _HVD_CATEGORY_BASE_URI,
                    "hvd_category_map",
                    upper_code=False,
                )
                if uri and uri not in uris:
                    uris.append(uri)

        if not uris:
            log.info(
                "%s Dataset marked as High Value but no HVD category URI could be derived from theme mapping",
                self.LOG_PREFIX,
            )
            return

        package_dict["hvd_category"] = uris
        log.debug("%s Applied hvd_category=%r based on POD theme/keyword", self.LOG_PREFIX, uris)

    # ------------------------------------------------------------------
    # conformsTo
    # ------------------------------------------------------------------

    def _drop_empty_conforms_to_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
    ) -> None:
        """
        Αφαιρεί το ``conforms_to`` που παράγει το rdflib από κενό POD
        ``conformsTo: ""`` (το κενό IRI γίνεται ``file:///...``).
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        if "conformsTo" not in source_dataset:
            return

        raw_value = source_dataset.get("conformsTo")
        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]

        if any(isinstance(value, str) and value.strip() for value in raw_values):
            return

        package_dict.pop("conforms_to", None)

        extras = package_dict.get("extras")
        if isinstance(extras, list):
            package_dict["extras"] = [
                extra
                for extra in extras
                if not (
                    isinstance(extra, dict)
                    and extra.get("key") in ("conforms_to", "dcat_conforms_to")
                )
            ]

        log.debug("%s Removed conforms_to generated from empty POD conformsTo", self.LOG_PREFIX)

    # ------------------------------------------------------------------
    # Επαφή / publisher
    # ------------------------------------------------------------------

    def _fix_contact_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
    ) -> None:
        """
        Συμπληρώνει το email επικοινωνίας από το ``contactPoint`` του data.json
        (το POD context χαρτογραφεί το ``hasEmail`` σε ``vcard:email`` και ο
        DCAT parser δεν το διαβάζει).
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        contact_point = source_dataset.get("contactPoint")
        if not contact_point:
            return

        if isinstance(contact_point, dict):
            entries = [contact_point]
        elif isinstance(contact_point, list):
            entries = [e for e in contact_point if isinstance(e, dict)]
        else:
            entries = []

        if not entries:
            return

        source_name = ""
        source_email = ""
        for entry in entries:
            if not source_name:
                source_name = (entry.get("fn") or "").strip()
            if not source_email:
                raw = (entry.get("hasEmail") or "").strip()
                source_email = raw.replace("mailto:", "") if raw else ""

        if not source_name and not source_email:
            return

        contacts = package_dict.get("contact")
        if isinstance(contacts, dict):
            contacts = [contacts]
        elif not isinstance(contacts, list):
            contacts = []

        matched = False
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            # Σύγκριση χωρίς κενά στην αρχή/τέλος (η πηγή μπορεί να έχει π.χ. "Τμήμα Χ ")
            if source_name and (contact.get("name") or "").strip() == source_name:
                if source_email and contact.get("email") != source_email:
                    contact["email"] = source_email
                matched = True
                break

        if not matched:
            new_contact: Dict[str, str] = {}
            if source_name:
                new_contact["name"] = source_name
            if source_email:
                new_contact["email"] = source_email
            if new_contact:
                contacts.append(new_contact)

        contacts = [c for c in contacts if isinstance(c, dict) and c]
        if contacts:
            package_dict["contact"] = contacts
            log.debug(
                "%s Fixed contact from POD source: name=%r email=%r",
                self.LOG_PREFIX,
                source_name,
                source_email,
            )

    def _fix_publisher_from_source(
        self,
        package_dict: Dict[str, Any],
        source_dataset: Dict[str, Any],
    ) -> None:
        """
        Συμπληρώνει το όνομα του publisher από το data.json (το POD context
        χαρτογραφεί το ``name`` σε ``skos:prefLabel`` αντί για ``foaf:name``).
        """
        if not isinstance(package_dict, dict) or not isinstance(source_dataset, dict):
            return

        source_pub = source_dataset.get("publisher")
        if not isinstance(source_pub, dict):
            return

        source_name = (source_pub.get("name") or "").strip()
        if not source_name:
            return

        publishers = package_dict.get("publisher")
        if isinstance(publishers, dict):
            publishers = [publishers]
        elif not isinstance(publishers, list):
            publishers = []

        if publishers:
            first = publishers[0] if isinstance(publishers[0], dict) else {}
            if not first.get("name"):
                first["name"] = source_name
                publishers[0] = first
        else:
            publishers = [{"name": source_name}]

        publishers = [p for p in publishers if isinstance(p, dict) and p]
        if publishers:
            package_dict["publisher"] = publishers
            log.debug("%s Fixed publisher from POD source: name=%r", self.LOG_PREFIX, source_name)

    # ------------------------------------------------------------------
    # Σχετικά URLs στην περιγραφή
    # ------------------------------------------------------------------

    def _fix_relative_urls_in_description(self, package_dict, config, harvest_object) -> None:
        """
        Κάνει απόλυτα τα σχετικά ``src="/..."`` των εικόνων στην περιγραφή,
        με βάση το relative_url_base. Τα ``src="//..."`` μένουν ως έχουν.
        """
        base = self._get_relative_url_base(config, harvest_object)
        if not base:
            return

        def _fix_img_src(value):
            if not isinstance(value, str):
                return value
            # Τα src="//host/..." (χωρίς πρωτόκολλο) δεν αλλάζουν
            return _RELATIVE_SRC_RE.sub(lambda m: f"{m.group(1)}{base}/", value)

        if "notes" in package_dict:
            package_dict["notes"] = _fix_img_src(package_dict.get("notes"))

        notes_translated = package_dict.get("notes_translated")
        if isinstance(notes_translated, dict):
            for lang, val in list(notes_translated.items()):
                notes_translated[lang] = _fix_img_src(val)

        # Αν η βασική κλάση έχει ήδη φτιάξει flattened πεδία, ενημερώνονται κι αυτά
        for key in ("notes_translated-el", "notes_translated-en"):
            if key in package_dict:
                package_dict[key] = _fix_img_src(package_dict.get(key))
