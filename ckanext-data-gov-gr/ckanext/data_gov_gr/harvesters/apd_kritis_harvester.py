# -*- coding: utf-8 -*-
from typing import Dict

from .pod_datajson_harvester import PodDataJsonHarvester

# Σταθερή αντιστοίχιση των POD `theme` της ΑΠΔ Κρήτης σε URIs κατηγοριών HVD
# του data.gov.gr (όπως είναι στο λεξιλόγιο "High-value dataset categories").
_APD_THEME_TO_HVD_CATEGORY: Dict[str, str] = {
    "Περιβάλλον": "http://data.europa.eu/bna/c_dd313021",
    "Ύδατα": "http://data.europa.eu/bna/c_dd313021",
    "Ενέργεια και Φυσικοί Πόροι": "http://data.europa.eu/bna/c_dd313021",
    "Χαρτογραφικά Δεδομένα Ψηφιακών Χαρτών": "http://data.europa.eu/bna/c_ac64a52d",
    "Χωροταξικός Σχεδιασμός": "http://data.europa.eu/bna/c_ac64a52d",
    "Μετεωρολογικοί - Υδρολογικοί Σταθμοί": "http://data.europa.eu/bna/c_164e0bf5",
    "Ιστορικά δεδομένα προγραμμάτων": "http://data.europa.eu/bna/c_e1da4e07",
}

# Σταθερή αντιστοίχιση των POD `theme` της ΑΠΔ Κρήτης σε EU Data Theme
# authority URIs (όπως είναι στο λεξιλόγιο "Data theme").
#
# Λεξιλόγιο (από το CKAN):
#   AGRI -> .../data-theme/AGRI
#   ECON -> .../data-theme/ECON
#   EDUC -> .../data-theme/EDUC
#   ENER -> .../data-theme/ENER
#   ENVI -> .../data-theme/ENVI
#   GOVE -> .../data-theme/GOVE
#   HEAL -> .../data-theme/HEAL
#   INTR -> .../data-theme/INTR
#   JUST -> .../data-theme/JUST
#   REGI -> .../data-theme/REGI
#   SOCI -> .../data-theme/SOCI
#   TECH -> .../data-theme/TECH
#   TRAN -> .../data-theme/TRAN
#
# Αποφάσεις αντιστοίχισης για τα themes της ΑΠΔ Κρήτης:
#   - Περιβάλλον, Ύδατα, Μετεωρολογικοί - Υδρολογικοί Σταθμοί
#       -> ENVI
#   - Ενέργεια και Φυσικοί Πόροι
#       -> ENER
#   - Χαρτογραφικά Δεδομένα Ψηφιακών Χαρτών, Χωροταξικός Σχεδιασμός
#       -> REGI
#   - Ιστορικά δεδομένα προγραμμάτων
#       -> SOCI
_APD_THEME_TO_DATA_THEME: Dict[str, str] = {
    "Περιβάλλον": "http://publications.europa.eu/resource/authority/data-theme/ENVI",
    "Ύδατα": "http://publications.europa.eu/resource/authority/data-theme/ENVI",
    "Μετεωρολογικοί - Υδρολογικοί Σταθμοί": "http://publications.europa.eu/resource/authority/data-theme/ENVI",
    "Ενέργεια και Φυσικοί Πόροι": "http://publications.europa.eu/resource/authority/data-theme/ENER",
    "Χαρτογραφικά Δεδομένα Ψηφιακών Χαρτών": "http://publications.europa.eu/resource/authority/data-theme/REGI",
    "Χωροταξικός Σχεδιασμός": "http://publications.europa.eu/resource/authority/data-theme/REGI",
    "Ιστορικά δεδομένα προγραμμάτων": "http://publications.europa.eu/resource/authority/data-theme/SOCI",
}


class ApdKritisHarvester(PodDataJsonHarvester):
    """
    Harvester DCAT/POD για την ΑΠΔ Κρήτης (data.apdkritis.gov.gr).

    Όλη η λογική βρίσκεται στον γενικό PodDataJsonHarvester. Εδώ μένουν μόνο
    το όνομα/τύπος του harvester (για να μη σπάσουν οι υπάρχουσες πηγές) και
    οι προεπιλογές της ΑΠΔ Κρήτης:

      - άδεια "cc-by" (και παραλλαγές) -> CC BY 4.0,
      - αντιστοίχιση των POD ``theme`` σε EU Data Theme και σε κατηγορία HVD
        (για datasets με λέξη-κλειδί "High Value Dataset"),
      - domain για τα σχετικά ``src`` των εικόνων στην περιγραφή,
      - διαδρομή του data.json όταν το URL της πηγής είναι η ρίζα του site.

    Η διαμόρφωση της πηγής (license_map, theme_map, hvd_category_map,
    hvd_keyword, relative_url_base κλπ) υπερισχύει των προεπιλογών.
    """

    LOG_PREFIX = "[APD KRITIS HARVESTER]"

    # Η ΑΠΔ Κρήτης δίνει "cc-by" σε όλα τα datasets· δεχόμαστε και παραλλαγές.
    DEFAULT_LICENSE_MAP = {
        "cc-by": "cc-by",
        "cc by": "cc-by",
        "cc_by": "cc-by",
        "creative commons attribution": "cc-by",
        "cc-by-4.0": "cc-by",
    }

    DEFAULT_THEME_MAP = _APD_THEME_TO_DATA_THEME
    DEFAULT_HVD_CATEGORY_MAP = _APD_THEME_TO_HVD_CATEGORY

    # Οι περιγραφές της ΑΠΔ Κρήτης έχουν εικόνες με σχετικά URLs,
    # π.χ. <img src="/sites/default/...">.
    DEFAULT_RELATIVE_URL_BASE = "https://data.apdkritis.gov.gr"

    # Όταν το URL της πηγής είναι η ρίζα του site, π.χ. https://data.apdkritis.gov.gr
    DEFAULT_CATALOG_PATH = "/sites/default/files/pod_data/data.json"

    def info(self):
        return {
            "name": "apd_kritis_harvester",
            "title": "APD Kritis DCAT/POD Harvester",
            "description": (
                "Harvester for APD Kritis POD data.json that propagates "
                "CC-BY licences to resources and maps High Value datasets "
                "to hvd_category."
            ),
            "form_config_interface": "Text",
            "show_config": True,
        }
