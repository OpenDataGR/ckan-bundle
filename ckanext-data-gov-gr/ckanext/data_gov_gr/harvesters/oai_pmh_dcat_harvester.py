# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
import unicodedata
from hashlib import sha1
from urllib.parse import urlencode

import requests
from ckan import model
from ckanext.dcat.processors import RDFParser, RDFParserException
from ckanext.harvest.model import HarvestObject, HarvestObjectExtra
from lxml import etree

from ckanext.data_gov_gr.harvesters.custom_dcat_harvester import (
    CustomDcatHarvester,
    harvest_local,
)

log = logging.getLogger(__name__)


OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/"}
DATASET_NAME_PREFIX_FROM_IDENTIFIER_CONFIG_KEY = "dataset_name_prefix_from_identifier"
DATASET_NAME_MAX_LENGTH_CONFIG_KEY = "dataset_name_max_length"
DEFAULT_DATASET_NAME_MAX_LENGTH = 100
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def normalize_ckan_name(value):
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-_")


class OaiPmhDcatHarvester(CustomDcatHarvester):
    """
    OAI-PMH harvester for endpoints that expose DCAT-AP RDF/XML records.

    The OAI-PMH response is only used as a transport wrapper. Each record's
    ``metadata/rdf:RDF`` payload is parsed with ckanext-dcat's RDFParser and
    then imported through CustomDcatHarvester / DCATRDFHarvester.
    """

    DEFAULT_METADATA_PREFIX = "dcat_ap"
    DEFAULT_RDF_FORMAT = "xml"
    DEFAULT_TIMEOUT = 60

    def __new__(cls, *args, **kwargs):
        # CustomDcatHarvester is also a SingletonPlugin. If it has already
        # been loaded, the inherited _instance would otherwise be reused here.
        if "_instance" not in cls.__dict__:
            cls._instance = object.__new__(cls)
        return cls._instance

    def info(self):
        return {
            "name": "oai_pmh_dcat_harvester",
            "title": "OAI-PMH DCAT-AP Harvester",
            "description": (
                "Harvests OAI-PMH ListRecords endpoints whose metadata payload "
                "is DCAT-AP RDF/XML."
            ),
            "form_config_interface": "Text",
            "show_config": True,
        }

    def validate_config(self, source_config):
        if not source_config:
            return json.dumps(
                {
                    "metadata_prefix": self.DEFAULT_METADATA_PREFIX,
                    "rdf_format": self.DEFAULT_RDF_FORMAT,
                }
            )

        try:
            config = json.loads(source_config)
        except ValueError as e:
            raise ValueError("OAI-PMH DCAT harvester config must be valid JSON: %s" % e)

        if not isinstance(config, dict):
            raise ValueError("OAI-PMH DCAT harvester config must be a JSON object")

        string_keys = (
            "metadata_prefix",
            "rdf_format",
            "set",
            "from",
            "until",
            "user_agent",
            DATASET_NAME_PREFIX_FROM_IDENTIFIER_CONFIG_KEY,
        )
        for key in string_keys:
            if key in config and config[key] is not None and not isinstance(config[key], str):
                raise ValueError("%s must be a string" % key)

        for key in ("timeout", DATASET_NAME_MAX_LENGTH_CONFIG_KEY):
            if key not in config:
                continue
            try:
                int_value = int(config[key])
            except (TypeError, ValueError):
                raise ValueError("%s must be an integer" % key)
            if int_value <= 0:
                raise ValueError("%s must be greater than zero" % key)

        return json.dumps(config)

    def gather_stage(self, harvest_job):
        log.info("OAI-PMH DCAT gather started for source: %s", harvest_job.source.url)

        config = self._config(harvest_job)
        harvest_local.user_agent = config.get("user_agent")

        object_ids = []
        guids_in_source = []
        self._names_taken = []

        source_dataset = model.Package.get(harvest_job.source.id)
        guid_to_package_id = self._existing_guid_to_package_id(harvest_job)

        next_url = self._build_oai_url(harvest_job.source.url, config)
        page_count = 0
        max_pages = config.get("max_pages")

        while next_url:
            page_count += 1
            if max_pages and page_count > int(max_pages):
                log.info("Reached configured OAI-PMH max_pages=%s", max_pages)
                break

            content = self._load_oai_page(next_url, harvest_job, config)
            if not content:
                break

            try:
                records, resumption_token = self._parse_oai_page(content, config)
            except Exception as e:
                self._save_gather_error(
                    "Could not parse OAI-PMH response from %s: %r / %s"
                    % (next_url, e, traceback.format_exc()),
                    harvest_job,
                )
                return []

            log.info(
                "OAI-PMH DCAT page %s: parsed %s active records",
                page_count,
                len(records),
            )

            for record in records:
                dataset = record["dataset"]
                self._prepare_dataset(dataset, record, source_dataset, harvest_job, config)

                guid = self._record_guid(record, dataset, source_dataset)
                if not guid:
                    self._save_gather_error(
                        "Could not get a unique identifier for OAI-PMH record: %r"
                        % record.get("oai_identifier"),
                        harvest_job,
                    )
                    continue

                guids_in_source.append(guid)
                self._append_unique_extra(dataset, "guid", guid)
                self._append_unique_extra(dataset, "oai_identifier", record.get("oai_identifier"))
                self._append_unique_extra(dataset, "oai_datestamp", record.get("datestamp"))
                self._append_unique_extra(dataset, "metadata_prefix", config["metadata_prefix"])

                extras = [
                    HarvestObjectExtra(
                        key="status",
                        value="change" if guid in guid_to_package_id else "new",
                    )
                ]
                obj_kwargs = {
                    "guid": guid,
                    "job": harvest_job,
                    "content": json.dumps(dataset),
                    "extras": extras,
                }
                if guid in guid_to_package_id:
                    obj_kwargs["package_id"] = guid_to_package_id[guid]

                obj = HarvestObject(**obj_kwargs)
                obj.save()
                object_ids.append(obj.id)

            if resumption_token:
                next_url = self._build_oai_url(
                    harvest_job.source.url,
                    config,
                    resumption_token=resumption_token,
                )
                if config.get("throttle_ms"):
                    time.sleep(int(config["throttle_ms"]) / 1000.0)
            else:
                next_url = None

        try:
            object_ids.extend(self._mark_datasets_for_deletion(guids_in_source, harvest_job))
        except Exception as e:
            log.warning("Error computing OAI-PMH DCAT deleted datasets: %s", e)

        log.info("OAI-PMH DCAT gather completed: %d objects", len(object_ids))
        return object_ids

    def fetch_stage(self, harvest_object):
        return True

    def _config(self, harvest_job):
        config = {}
        if harvest_job and harvest_job.source and harvest_job.source.config:
            try:
                config = json.loads(harvest_job.source.config) or {}
            except ValueError:
                config = {}

        config.setdefault("metadata_prefix", self.DEFAULT_METADATA_PREFIX)
        config.setdefault("rdf_format", self.DEFAULT_RDF_FORMAT)
        config.setdefault("timeout", self.DEFAULT_TIMEOUT)
        return config

    def _build_oai_url(self, base_url, config, resumption_token=None):
        params = {"verb": "ListRecords"}
        if resumption_token:
            params["resumptionToken"] = resumption_token
        else:
            params["metadataPrefix"] = config["metadata_prefix"]
            for key in ("set", "from", "until"):
                value = config.get(key)
                if value:
                    params[key] = value

        separator = "&" if "?" in base_url else "?"
        return "%s%s%s" % (base_url.rstrip("?&"), separator, urlencode(params))

    def _load_oai_page(self, url, harvest_job, config):
        if not str(url).lower().startswith("http"):
            if os.path.exists(url):
                with open(url, "rb") as f:
                    return f.read()
            self._save_gather_error("Could not read local OAI-PMH file: %s" % url, harvest_job)
            return None

        try:
            session = requests.Session()
            user_agent = config.get("user_agent")
            if user_agent:
                session.headers.update({"User-Agent": str(user_agent)})

            username = config.get("username")
            password = config.get("password")
            auth = (username, password) if username and password else None

            response = session.get(url, auth=auth, timeout=int(config["timeout"]))
            response.raise_for_status()
            return response.content
        except requests.RequestException as e:
            self._save_gather_error(
                "Could not fetch OAI-PMH URL %s: %s" % (url, e),
                harvest_job,
            )
            return None

    def _parse_oai_page(self, content, config):
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
        xml_content = content.encode("utf-8") if isinstance(content, str) else content
        root = etree.fromstring(xml_content, parser)

        errors = root.xpath("./oai:error", namespaces=OAI_NS)
        if errors:
            messages = []
            for error in errors:
                code = error.get("code")
                text = (error.text or "").strip()
                messages.append("%s: %s" % (code, text) if code else text)
            raise ValueError("; ".join(messages))

        records = []
        for record_el in root.xpath(".//oai:ListRecords/oai:record", namespaces=OAI_NS):
            header = record_el.find("oai:header", namespaces=OAI_NS)
            if header is None:
                continue
            if header.get("status") == "deleted":
                continue

            oai_identifier = self._first_text(header, "oai:identifier")
            datestamp = self._first_text(header, "oai:datestamp")
            rdf_elements = record_el.xpath(
                "./oai:metadata/*[local-name()='RDF']", namespaces=OAI_NS
            )
            if not rdf_elements:
                log.warning("Skipping OAI-PMH record without rdf:RDF metadata: %s", oai_identifier)
                continue

            rdf_xml = etree.tostring(rdf_elements[0], encoding="unicode")
            dataset = self._parse_rdf_dataset(rdf_xml, config)
            if not dataset:
                log.warning(
                    "Skipping OAI-PMH record without parsed DCAT dataset: %s",
                    oai_identifier,
                )
                continue

            records.append(
                {
                    "oai_identifier": oai_identifier,
                    "datestamp": datestamp,
                    "rdf_xml": rdf_xml,
                    "dataset": dataset,
                }
            )

        token = self._first_text(root, ".//oai:ListRecords/oai:resumptionToken")
        return records, token

    def _parse_rdf_dataset(self, rdf_xml, config):
        parser = RDFParser()
        try:
            parser.parse(rdf_xml, _format=config.get("rdf_format") or self.DEFAULT_RDF_FORMAT)
        except RDFParserException as e:
            log.warning("Could not parse OAI-PMH DCAT RDF/XML record: %s", e)
            return None

        for dataset in parser.datasets():
            return dataset or None
        return None

    def _prepare_dataset(self, dataset, record, source_dataset, harvest_job, config=None):
        config = config or {}
        dataset.setdefault("extras", [])

        if not dataset.get("name"):
            dataset["name"] = (
                self._dataset_name_from_identifier_config(dataset, record, config)
                or self._dataset_name_from_title(dataset, source_dataset)
            )

        if dataset["name"] in self._names_taken:
            base_name = dataset["name"]
            suffix = 1
            while "%s-%s" % (base_name, suffix) in self._names_taken:
                suffix += 1
            dataset["name"] = "%s-%s" % (base_name, suffix)
        self._names_taken.append(dataset["name"])

        if not dataset.get("owner_org") and source_dataset is not None:
            owner_org = getattr(source_dataset, "owner_org", None)
            if owner_org:
                dataset["owner_org"] = owner_org

        datestamp = record.get("datestamp")
        if datestamp and not dataset.get("metadata_modified"):
            dataset["metadata_modified"] = datestamp

        self._ensure_resource_names(dataset)

    def _dataset_name_from_identifier_config(self, dataset, record, config):
        prefix = config.get(DATASET_NAME_PREFIX_FROM_IDENTIFIER_CONFIG_KEY)
        if prefix is None:
            return None

        identifiers = (
            self._dataset_identifier(dataset)
            or "",
            record.get("oai_identifier") or "",
            self._extra_value(dataset, "uri") or "",
        )
        uuid = None
        for identifier in identifiers:
            uuid = self._uuid_from_identifier(identifier)
            if uuid:
                break
        if not uuid:
            return None

        return self._dataset_name_from_identifier(prefix, uuid, config)

    def _dataset_name_from_identifier(self, prefix, identifier, config):
        dataset_name = normalize_ckan_name("%s%s" % (prefix or "", identifier))
        max_length = self._dataset_name_max_length(config)
        if not dataset_name or len(dataset_name) <= max_length:
            return dataset_name

        digest = sha1(dataset_name.encode("utf-8")).hexdigest()[:10]
        suffix = "-%s" % digest
        prefix_length = max_length - len(suffix)
        if prefix_length <= 0:
            return digest[:max_length]

        trimmed = dataset_name[:prefix_length].strip("-_")
        if not trimmed:
            return digest[:max_length]
        return "%s%s" % (trimmed, suffix)

    def _dataset_name_max_length(self, config):
        try:
            max_length = int(config.get(
                DATASET_NAME_MAX_LENGTH_CONFIG_KEY,
                DEFAULT_DATASET_NAME_MAX_LENGTH,
            ))
        except (TypeError, ValueError):
            max_length = DEFAULT_DATASET_NAME_MAX_LENGTH
        return max(1, max_length)

    def _dataset_identifier(self, dataset):
        return (
            self._get_dict_value(dataset, "identifier")
            or self._extra_value(dataset, "identifier")
            or self._get_dict_value(dataset, "uri")
            or self._extra_value(dataset, "uri")
        )

    def _uuid_from_identifier(self, identifier):
        if not identifier:
            return None
        match = UUID_RE.search(str(identifier))
        if not match:
            return None
        return match.group(0).lower()

    def _dataset_name_from_title(self, dataset, source_dataset):
        title = self._best_title(dataset)
        raw_name = self._gen_new_name(title)
        if not raw_name:
            raw_name = "dataset"

        harvest_prefix = None
        if source_dataset is not None:
            harvest_prefix = getattr(source_dataset, "name", None)
        if not harvest_prefix:
            harvest_prefix = "oai-pmh"

        return "%s-%s" % (harvest_prefix, raw_name)

    def _ensure_resource_names(self, dataset):
        resources = dataset.get("resources")
        if not isinstance(resources, list) or not resources:
            return

        title = self._best_title(dataset)
        for index, resource in enumerate(resources, 1):
            if not isinstance(resource, dict) or resource.get("name") or not title:
                continue

            if len(resources) == 1:
                resource["name"] = title
            else:
                resource["name"] = "%s - resource %s" % (title, index)

    def _best_title(self, dataset):
        title = dataset.get("title")
        if title:
            return title

        translated = dataset.get("title_translated")
        if isinstance(translated, dict):
            return translated.get("el") or translated.get("en") or "Untitled Dataset"

        return (
            self._get_dict_value(dataset, "identifier")
            or self._get_dict_value(dataset, "uri")
            or "Untitled Dataset"
        )

    def _record_guid(self, record, dataset, source_dataset):
        guid = self._get_guid(
            dataset,
            source_url=getattr(source_dataset, "url", None) if source_dataset else None,
        )
        return guid or record.get("oai_identifier")

    def _append_unique_extra(self, dataset, key, value):
        if value is None:
            return
        extras = dataset.setdefault("extras", [])
        if any(isinstance(extra, dict) and extra.get("key") == key for extra in extras):
            return
        extras.append({"key": key, "value": value})

    def _extra_value(self, dataset, key):
        for extra in dataset.get("extras", []) or []:
            if isinstance(extra, dict) and extra.get("key") == key:
                return extra.get("value")
        return None

    def _existing_guid_to_package_id(self, harvest_job):
        query = (
            model.Session.query(HarvestObject.guid, HarvestObject.package_id)
            .filter(HarvestObject.current == True)
            .filter(HarvestObject.harvest_source_id == harvest_job.source.id)
        )
        return {guid: package_id for guid, package_id in query}

    def _first_text(self, element, xpath):
        values = element.xpath(xpath, namespaces=OAI_NS)
        if not values:
            return None
        value = values[0]
        if isinstance(value, etree._Element):
            return (value.text or "").strip() or None
        return str(value).strip() or None
