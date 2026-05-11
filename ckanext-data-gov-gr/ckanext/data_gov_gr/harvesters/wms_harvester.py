# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import re
import unicodedata
from hashlib import sha1
from typing import Any

import ckan.plugins.toolkit as toolkit
import requests
from ckan import model
from ckan.model import Session
from ckanext.harvest.harvesters import HarvesterBase
from ckanext.harvest.model import HarvestObject, HarvestObjectExtra
from lxml import etree

from ckanext.data_gov_gr.logic.harvest_mapping import (
    apply_default_dataset_fields_from_config,
    apply_default_resource_fields_from_config,
    ensure_applicable_legislation,
    preserve_resource_ids_by_url,
)

log = logging.getLogger(__name__)


WMS_NS = {
    "wms": "http://www.opengis.net/wms",
    "xlink": "http://www.w3.org/1999/xlink",
}

DATASET_NAME_PREFIX_CONFIG_KEY = "dataset_name_prefix_from_layer_name"
LEGACY_DATASET_NAME_PREFIX_CONFIG_KEY = "dataset_name_prefix_from_file_identifier"
DATASET_NAME_MAX_LENGTH_CONFIG_KEY = "dataset_name_max_length"
WMS_PREVIEW_BASE_URL_CONFIG_KEY = "wms_preview_base_url"
WMS_CAPABILITIES_URL_CONFIG_KEY = "wms_capabilities_url"
WFS_CAPABILITIES_URL_CONFIG_KEY = "wfs_capabilities_url"
DEFAULT_THEME_CONFIG_KEY = "default_theme"
GATHER_LOG_EVERY_CONFIG_KEY = "gather_log_every"
INCLUDE_LAYER_NAME_KEYWORDS_CONFIG_KEY = "include_layer_name_keywords"
SKIP_KEYWORDS_MATCHING_CONFIG_KEY = "skip_keywords_matching"
DEFAULT_TAGS_CONFIG_KEY = "default_tags"
SKIP_DATASET_WHEN_TITLE_MATCHES_LAYER_NAME_CONFIG_KEY = (
    "skip_dataset_when_title_matches_layer_name"
)
DEFAULT_TIMEOUT = 60
DEFAULT_DATASET_NAME_MAX_LENGTH = 100

PUBLIC_ACCESS_RIGHTS = "http://publications.europa.eu/resource/authority/access-right/PUBLIC"
GEOSPATIAL_DCAT_TYPE = "http://publications.europa.eu/resource/authority/dataset-type/GEOSPATIAL"


def _text(element, xpath: str) -> str:
    values = element.xpath(xpath, namespaces=WMS_NS)
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


def normalize_ckan_name(value: str) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-_")


def normalize_ckan_tag(value: str) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", str(value))
    lowered = normalized.strip().lower().replace(":", "-")
    slug = re.sub(r"[^\w-]+", "-", lowered, flags=re.UNICODE)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-_")


def _translated(value: str, fallback: str = "") -> dict[str, str]:
    text = (value or fallback or "").strip()
    return {
        "el": text,
        "en": text,
    }


def _bbox_geojson(bbox: dict[str, float]) -> str:
    west = bbox["west"]
    east = bbox["east"]
    south = bbox["south"]
    north = bbox["north"]
    return json.dumps({
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [west, north],
            [east, north],
            [east, south],
            [west, south],
        ]],
    })


def _centroid_geojson(bbox: dict[str, float]) -> str:
    west = bbox["west"]
    east = bbox["east"]
    south = bbox["south"]
    north = bbox["north"]
    return json.dumps({
        "type": "Point",
        "coordinates": [
            (west + east) / 2.0,
            (south + north) / 2.0,
        ],
    })


def _parse_float(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_ex_geographic_bbox(layer) -> dict[str, float] | None:
    bbox_el = layer.find("wms:EX_GeographicBoundingBox", namespaces=WMS_NS)
    if bbox_el is None:
        return None

    values = {
        "west": _parse_float(_text(bbox_el, "./wms:westBoundLongitude/text()")),
        "east": _parse_float(_text(bbox_el, "./wms:eastBoundLongitude/text()")),
        "south": _parse_float(_text(bbox_el, "./wms:southBoundLatitude/text()")),
        "north": _parse_float(_text(bbox_el, "./wms:northBoundLatitude/text()")),
    }
    if any(value is None for value in values.values()):
        return None

    return values


def parse_wms_capabilities(xml_content: bytes | str) -> dict[str, Any]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")

    tree = etree.fromstring(xml_content, parser=parser)
    service = tree.find("wms:Service", namespaces=WMS_NS)
    service_title = _text(service, "./wms:Title/text()") if service is not None else ""

    layers = []
    for layer in tree.xpath("//wms:Layer[wms:Name]", namespaces=WMS_NS):
        name = _text(layer, "./wms:Name/text()")
        if not name:
            continue

        keywords = [
            str(value).strip()
            for value in layer.xpath(
                "./wms:KeywordList/wms:Keyword/text()",
                namespaces=WMS_NS,
            )
            if str(value).strip()
        ]
        crs = [
            str(value).strip()
            for value in layer.xpath("./wms:CRS/text()", namespaces=WMS_NS)
            if str(value).strip()
        ]
        legend_urls = [
            str(value).strip()
            for value in layer.xpath(
                "./wms:Style/wms:LegendURL/wms:OnlineResource/@xlink:href",
                namespaces=WMS_NS,
            )
            if str(value).strip()
        ]

        layers.append({
            "name": name,
            "title": _text(layer, "./wms:Title/text()") or name,
            "abstract": _text(layer, "./wms:Abstract/text()"),
            "keywords": keywords,
            "crs": crs,
            "bbox": _parse_ex_geographic_bbox(layer),
            "legend_url": legend_urls[0] if legend_urls else "",
        })

    return {
        "service_title": service_title,
        "layers": layers,
    }


class WmsCapabilitiesHarvester(HarvesterBase):
    def info(self):
        return {
            "name": "wms_capabilities_harvester",
            "title": "WMS Capabilities Harvester",
            "description": (
                "Creates one CKAN dataset per named WMS layer from a "
                "GetCapabilities document."
            ),
            "form_config_interface": "Text",
            "show_config": False,
        }

    def validate_config(self, source_config):
        if not source_config:
            return source_config

        try:
            config = json.loads(source_config)
        except ValueError as e:
            raise ValueError("WMS harvester config must be valid JSON: %s" % e)

        if not isinstance(config, dict):
            raise ValueError("WMS harvester config must be a JSON object")

        return source_config

    def gather_stage(self, harvest_job):
        log.info("WMS capabilities gather started for source: %s", harvest_job.source.url)
        config = self._config(harvest_job)
        capabilities_xml = self._load_capabilities(harvest_job, config)
        if not capabilities_xml:
            return []

        try:
            parsed = parse_wms_capabilities(capabilities_xml)
        except Exception as e:
            self._save_gather_error("Could not parse WMS capabilities: %s" % e, harvest_job)
            log.exception("Could not parse WMS capabilities")
            return []

        prefix = self._dataset_name_prefix(config)
        log_every = self._gather_log_every(config)
        skip_title_matches_layer_name = bool(
            config.get(SKIP_DATASET_WHEN_TITLE_MATCHES_LAYER_NAME_CONFIG_KEY)
        )
        guid_to_package_id = self._existing_guid_to_package_id(harvest_job)
        object_ids = []
        guids_in_source = []
        total_layers = len(parsed["layers"])
        skipped_count = 0

        for index, layer in enumerate(parsed["layers"], start=1):
            if skip_title_matches_layer_name and self._title_matches_layer_name(layer):
                skipped_count += 1
                if skipped_count == 1 or skipped_count % log_every == 0:
                    log.info(
                        "Skipping WMS layer with non-descriptive title: "
                        "%d skipped so far; layer=%s title=%s",
                        skipped_count,
                        layer["name"],
                        layer.get("title") or "",
                    )
                continue

            dataset_name = self._dataset_name_from_layer_name(
                prefix,
                layer["name"],
                config,
            )
            if not dataset_name:
                self._save_gather_error(
                    "Skipping WMS layer with invalid CKAN name: %s" % layer["name"],
                    harvest_job,
                )
                continue

            guid = dataset_name
            guids_in_source.append(guid)

            if index == 1 or index == total_layers or index % log_every == 0:
                log.info(
                    "WMS capabilities gather progress: %d/%d layer=%s guid=%s",
                    index,
                    total_layers,
                    layer["name"],
                    guid,
                )

            payload = {
                "layer": layer,
                "dataset_name": dataset_name,
                "guid": guid,
                "service_title": parsed.get("service_title") or "",
                "source_url": harvest_job.source.url,
            }

            extras = [HarvestObjectExtra(key="status", value="change" if guid in guid_to_package_id else "new")]
            obj_kwargs = {
                "guid": guid,
                "job": harvest_job,
                "content": json.dumps(payload, ensure_ascii=False),
                "extras": extras,
            }
            if guid in guid_to_package_id:
                obj_kwargs["package_id"] = guid_to_package_id[guid]

            obj = HarvestObject(**obj_kwargs)
            obj.save()
            object_ids.append(obj.id)

        try:
            object_ids.extend(self._mark_datasets_for_deletion(guids_in_source, harvest_job))
        except Exception as e:
            log.warning("Error computing WMS deleted datasets: %s", e)

        log.info("WMS capabilities gather completed: %d objects", len(object_ids))
        if skipped_count:
            log.info(
                "WMS capabilities gather skipped %d layers with titles matching "
                "their layer names",
                skipped_count,
            )
        return object_ids

    def fetch_stage(self, harvest_object):
        return True

    def import_stage(self, harvest_object):
        status = self._get_object_extra(harvest_object, "status")
        if status == "delete":
            return self._delete_package_for_harvest_object(harvest_object)

        try:
            payload = json.loads(harvest_object.content)
            config = self._config_from_harvest_object(harvest_object)
            package_dict = self._package_dict_from_payload(payload, harvest_object, config)
            return self._create_or_update_package(package_dict, harvest_object)
        except Exception as e:
            log.exception("Error importing WMS layer")
            self._save_object_error(str(e), harvest_object, "Import")
            return False

    def _get_object_extra(self, harvest_object, key: str) -> str | None:
        for extra in getattr(harvest_object, "extras", []) or []:
            if getattr(extra, "key", None) == key:
                return getattr(extra, "value", None)
        return None

    def _delete_package_for_harvest_object(self, harvest_object):
        context = {
            "model": model,
            "session": model.Session,
            "user": self._get_user_name(),
            "ignore_auth": True,
        }
        try:
            toolkit.get_action("package_delete")(context, {"id": harvest_object.package_id})
            log.info(
                "Deleted package %s with WMS guid %s",
                harvest_object.package_id,
                harvest_object.guid,
            )
        except toolkit.ObjectNotFound:
            log.info("Package %s already deleted.", harvest_object.package_id)

        return True

    def _config(self, harvest_job) -> dict[str, Any]:
        if not harvest_job or not harvest_job.source or not harvest_job.source.config:
            return {}
        try:
            config = json.loads(harvest_job.source.config)
            return config if isinstance(config, dict) else {}
        except ValueError:
            return {}

    def _config_from_harvest_object(self, harvest_object) -> dict[str, Any]:
        source = getattr(getattr(harvest_object, "job", None), "source", None)
        if source is None:
            source = getattr(harvest_object, "source", None)
        if source is None or not getattr(source, "config", None):
            return {}
        try:
            config = json.loads(source.config)
            return config if isinstance(config, dict) else {}
        except ValueError:
            return {}

    def _dataset_name_prefix(self, config: dict[str, Any]) -> str:
        return str(
            config.get(DATASET_NAME_PREFIX_CONFIG_KEY)
            or config.get(LEGACY_DATASET_NAME_PREFIX_CONFIG_KEY)
            or ""
        )

    def _dataset_name_from_layer_name(
        self,
        prefix: str,
        layer_name: str,
        config: dict[str, Any],
    ) -> str:
        dataset_name = normalize_ckan_name("%s%s" % (prefix, layer_name))
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

    def _dataset_name_max_length(self, config: dict[str, Any]) -> int:
        try:
            max_length = int(config.get(
                DATASET_NAME_MAX_LENGTH_CONFIG_KEY,
                DEFAULT_DATASET_NAME_MAX_LENGTH,
            ))
        except (TypeError, ValueError):
            max_length = DEFAULT_DATASET_NAME_MAX_LENGTH
        return max(1, max_length)

    def _title_matches_layer_name(self, layer: dict[str, Any]) -> bool:
        layer_name = str(layer.get("name") or "").strip()
        title = str(layer.get("title") or "").strip()
        if not layer_name or not title:
            return False

        local_layer_name = layer_name.split(":", 1)[-1]
        normalized_title = self._normalize_title_for_match(title)
        return normalized_title in {
            self._normalize_title_for_match(layer_name),
            self._normalize_title_for_match(local_layer_name),
        }

    def _normalize_title_for_match(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
        return re.sub(r"[-_]+", "-", normalized)

    def _load_capabilities(self, harvest_job, config: dict[str, Any]) -> bytes | None:
        capabilities_file = str(config.get("capabilities_file") or "").strip()
        if capabilities_file:
            try:
                with open(capabilities_file, "rb") as fh:
                    return fh.read()
            except Exception as e:
                self._save_gather_error(
                    "Could not read WMS capabilities file %s: %s" % (capabilities_file, e),
                    harvest_job,
                )
                return None

        url = str(config.get(WMS_CAPABILITIES_URL_CONFIG_KEY) or harvest_job.source.url or "").strip()
        if not url:
            self._save_gather_error("No WMS capabilities URL configured", harvest_job)
            return None

        try:
            response = requests.get(
                url,
                headers=self._request_headers(config),
                timeout=self._request_timeout(config),
            )
            response.raise_for_status()
            return response.content
        except Exception as e:
            self._save_gather_error("Could not fetch WMS capabilities %s: %s" % (url, e), harvest_job)
            return None

    def _request_headers(self, config: dict[str, Any]) -> dict[str, str]:
        user_agent = str(config.get("user_agent") or "").strip()
        if not user_agent:
            return {}
        return {"User-Agent": user_agent}

    def _request_timeout(self, config: dict[str, Any]) -> int:
        try:
            timeout = int(config.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        return max(1, timeout)

    def _gather_log_every(self, config: dict[str, Any]) -> int:
        try:
            log_every = int(config.get(GATHER_LOG_EVERY_CONFIG_KEY) or 100)
        except (TypeError, ValueError):
            log_every = 100
        return max(1, log_every)

    def _existing_guid_to_package_id(self, harvest_job) -> dict[str, str]:
        query = (
            model.Session.query(HarvestObject.guid, HarvestObject.package_id)
            .filter(HarvestObject.current == True)
            .filter(HarvestObject.harvest_source_id == harvest_job.source.id)
        )
        return {guid: package_id for guid, package_id in query}

    def _mark_datasets_for_deletion(self, guids_in_source, harvest_job):
        object_ids = []
        guid_to_package_id = self._existing_guid_to_package_id(harvest_job)
        guids_to_delete = set(guid_to_package_id.keys()) - set(guids_in_source)

        for guid in guids_to_delete:
            obj = HarvestObject(
                guid=guid,
                job=harvest_job,
                package_id=guid_to_package_id[guid],
                extras=[HarvestObjectExtra(key="status", value="delete")],
            )
            model.Session.query(HarvestObject).filter_by(guid=guid).update(
                {"current": False},
                False,
            )
            obj.save()
            object_ids.append(obj.id)

        return object_ids

    def _package_dict_from_payload(
        self,
        payload: dict[str, Any],
        harvest_object,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        layer = payload["layer"]
        layer_name = layer["name"]
        title = layer.get("title") or layer_name
        notes = layer.get("abstract") or title

        package_dict = {
            "name": payload["dataset_name"],
            "title": title,
            "title_translated": _translated(title, layer_name),
            "notes": notes,
            "notes_translated": _translated(notes, title),
            "private": bool(config.get("private", False)),
            "tag_string": self._tag_string(layer, config),
            "access_rights": PUBLIC_ACCESS_RIGHTS,
            "dcat_type": [GEOSPATIAL_DCAT_TYPE],
            "resources": self._resources(layer, payload, config),
            "extras": [
                {"key": "guid", "value": payload["guid"]},
                {"key": "wms_layer_name", "value": layer_name},
            ],
        }

        source_pkg = self._source_package(harvest_object)
        if source_pkg and source_pkg.owner_org:
            package_dict["owner_org"] = source_pkg.owner_org

        if layer.get("bbox"):
            package_dict["spatial_coverage"] = [{
                "uri": "",
                "text": "",
                "geom": "",
                "bbox": _bbox_geojson(layer["bbox"]),
                "centroid": _centroid_geojson(layer["bbox"]),
            }]

        themes = config.get(DEFAULT_THEME_CONFIG_KEY)
        if isinstance(themes, list) and themes:
            package_dict["theme"] = themes

        apply_default_dataset_fields_from_config(package_dict, harvest_object)
        ensure_applicable_legislation(package_dict, protected=False)
        apply_default_resource_fields_from_config(package_dict, harvest_object)
        preserve_resource_ids_by_url(package_dict, harvest_object)
        return package_dict

    def _source_package(self, harvest_object):
        source = getattr(getattr(harvest_object, "job", None), "source", None)
        if source is None:
            source = getattr(harvest_object, "source", None)
        source_id = getattr(source, "id", None)
        return model.Package.get(source_id) if source_id else None

    def _tag_string(self, layer: dict[str, Any], config: dict[str, Any]) -> str:
        tags = []
        layer_name = str(layer.get("name") or "").strip()
        local_layer_name = layer_name.split(":", 1)[-1] if layer_name else ""
        include_layer_name_keywords = bool(
            config.get(INCLUDE_LAYER_NAME_KEYWORDS_CONFIG_KEY)
        )
        skip_keyword_patterns = self._compiled_skip_keyword_patterns(config)
        skipped_values = {
            layer_name.lower(),
            local_layer_name.lower(),
        }
        for value in layer.get("keywords") or []:
            value = str(value or "").strip()
            if not value:
                continue
            if not include_layer_name_keywords and value.lower() in skipped_values:
                continue
            tag = normalize_ckan_tag(value)
            if self._keyword_matches_any_pattern(value, skip_keyword_patterns):
                continue
            if self._keyword_matches_any_pattern(tag, skip_keyword_patterns):
                continue
            if len(tag) < 2:
                continue
            if tag and tag not in tags:
                tags.append(tag)
        for tag in self._default_tags(config):
            if tag not in tags:
                tags.append(tag)
        return ", ".join(tags)

    def _default_tags(self, config: dict[str, Any]) -> list[str]:
        raw_tags = config.get(DEFAULT_TAGS_CONFIG_KEY)
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        if not isinstance(raw_tags, list):
            return []

        tags = []
        for value in raw_tags:
            value = str(value or "").strip()
            if not value:
                continue
            tag = normalize_ckan_tag(value)
            if len(tag) < 2:
                continue
            if tag and tag not in tags:
                tags.append(tag)
        return tags

    def _compiled_skip_keyword_patterns(self, config: dict[str, Any]) -> list[Any]:
        raw_patterns = config.get(SKIP_KEYWORDS_MATCHING_CONFIG_KEY)
        if isinstance(raw_patterns, str):
            raw_patterns = [raw_patterns]
        if not isinstance(raw_patterns, list):
            return []

        patterns = []
        for raw_pattern in raw_patterns:
            if not isinstance(raw_pattern, str) or not raw_pattern.strip():
                continue
            try:
                patterns.append(re.compile(raw_pattern.strip(), re.IGNORECASE))
            except re.error as e:
                log.warning(
                    "Ignoring invalid WMS keyword skip regex %r: %s",
                    raw_pattern,
                    e,
                )
        return patterns

    def _keyword_matches_any_pattern(self, keyword: str, patterns: list[Any]) -> bool:
        return any(pattern.search(keyword) for pattern in patterns)

    def _resources(
        self,
        layer: dict[str, Any],
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        layer_name = layer["name"]
        source_url = payload.get("source_url") or ""
        wms_capabilities_url = str(
            config.get(WMS_CAPABILITIES_URL_CONFIG_KEY) or source_url
        ).strip()
        wfs_capabilities_url = str(config.get(WFS_CAPABILITIES_URL_CONFIG_KEY) or "").strip()
        wms_preview_base_url = str(config.get(WMS_PREVIEW_BASE_URL_CONFIG_KEY) or "").strip()

        resources = []
        if wms_preview_base_url:
            resources.append(self._resource(
                url="%s%s" % (wms_preview_base_url, layer_name),
                layer_name=layer_name,
                title_el="Προεπισκόπηση WMS layer - %s" % layer_name,
                title_en="WMS layer preview - %s" % layer_name,
                description_el="Προεπισκόπηση του WMS layer %s." % layer_name,
                description_en="Preview of WMS layer %s." % layer_name,
                resource_format="WMS",
                protocol="OGC:WMS",
            ))

        if wms_capabilities_url:
            resources.append(self._resource(
                url=wms_capabilities_url,
                layer_name=layer_name,
                title_el="WMS capabilities document - %s" % layer_name,
                title_en="WMS capabilities document - %s" % layer_name,
                description_el=(
                    "WMS GetCapabilities document που περιγράφει και το layer %s."
                    % layer_name
                ),
                description_en=(
                    "WMS GetCapabilities document that includes layer %s."
                    % layer_name
                ),
                resource_format="XML",
                protocol="OGC:WMS",
            ))

        if wfs_capabilities_url:
            resources.append(self._resource(
                url=wfs_capabilities_url,
                layer_name=layer_name,
                title_el="WFS capabilities document - %s" % layer_name,
                title_en="WFS capabilities document - %s" % layer_name,
                description_el=(
                    "WFS GetCapabilities document που μπορεί να χρησιμοποιηθεί για "
                    "αναζήτηση του layer %s."
                    % layer_name
                ),
                description_en=(
                    "WFS GetCapabilities document that can be used to look up layer %s."
                    % layer_name
                ),
                resource_format="XML",
                protocol="OGC:WFS",
            ))

        return resources

    def _resource(
        self,
        *,
        url: str,
        layer_name: str,
        title_el: str,
        title_en: str,
        description_el: str,
        description_en: str,
        resource_format: str,
        protocol: str,
    ) -> dict[str, Any]:
        return {
            "url": url,
            "name": layer_name,
            "name_translated": {
                "el": title_el,
                "en": title_en,
            },
            "description_translated": {
                "el": description_el,
                "en": description_en,
            },
            "format": resource_format,
            "resource_locator_protocol": protocol,
            "access_url": url,
        }

    def _create_or_update_package(self, package_dict, harvest_object):
        user_name = self._get_user_name()
        context = {
            "model": model,
            "session": Session,
            "user": user_name,
            "ignore_auth": True,
        }

        try:
            if getattr(harvest_object, "package_id", None):
                package_dict["id"] = harvest_object.package_id
            existing_package_dict = self._find_existing_package(package_dict)
            package_dict["id"] = existing_package_dict["id"]
            package_dict["name"] = existing_package_dict["name"]
            new_package = toolkit.get_action("package_update")(context, package_dict)
        except (toolkit.ObjectNotFound, KeyError):
            new_package = toolkit.get_action("package_create")(context, package_dict)
        except toolkit.ValidationError as e:
            log.exception("Invalid WMS package with GUID %s", harvest_object.guid)
            self._save_object_error(
                "Invalid package with GUID %s: %s" % (harvest_object.guid, e.error_dict),
                harvest_object,
                "Import",
            )
            return False

        Session.query(HarvestObject).filter(
            HarvestObject.package_id == new_package["id"],
        ).update({"current": False})

        harvest_object.package_id = new_package["id"]
        harvest_object.current = True
        harvest_object.save()
        Session.commit()
        return True
