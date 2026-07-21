import json
import logging
from types import SimpleNamespace

from rdflib import Graph

from ckanext.data_gov_gr.harvesters import custom_dcat_harvester
from ckanext.data_gov_gr.harvesters.custom_dcat_harvester import CustomDcatHarvester


def test_resource_validation_preserves_rdf_xml_from_mimetype():
    harvester = CustomDcatHarvester()
    package_dict = {
        "name": "example",
        "resources": [
            {
                "name": "Export in RDF/XML",
                "url": "https://example.org/resource/xml",
                "format": "RDF",
                "mimetype": "https://www.iana.org/assignments/media-types/application/rdf+xml",
            }
        ],
    }

    harvester._fix_resource_validation(package_dict)

    assert package_dict["resources"][0]["format"] == "RDF_XML"


def test_log_fetch_progress_logs_current_object_position(monkeypatch, caplog):
    counts = iter([10, 3])

    class Query:
        def __init__(self, count):
            self._count = count

        def filter(self, *args):
            return self

        def count(self):
            return self._count

    def query(_model):
        return Query(next(counts))

    monkeypatch.setattr(
        custom_dcat_harvester.model,
        "Session",
        SimpleNamespace(query=query),
    )

    harvester = CustomDcatHarvester()
    harvest_object = SimpleNamespace(harvest_job_id="job-1", guid="dataset-guid")

    with caplog.at_level(logging.INFO, logger=custom_dcat_harvester.log.name):
        harvester._log_fetch_progress(harvest_object)

    assert "[DCAT] Processing 4/10: guid=dataset-guid" in caplog.text


def test_resource_validation_preserves_json_ld_from_mimetype():
    harvester = CustomDcatHarvester()
    package_dict = {
        "name": "example",
        "resources": [
            {
                "name": "Export in JSON-LD",
                "url": "https://example.org/resource/json",
                "format": "JSON",
                "mimetype": "https://www.iana.org/assignments/media-types/application/ld+json",
            }
        ],
    }

    harvester._fix_resource_validation(package_dict)

    assert package_dict["resources"][0]["format"] == "JSON_LD"


def test_resource_validation_uses_file_type_uri_code():
    harvester = CustomDcatHarvester()
    package_dict = {
        "name": "example",
        "resources": [
            {
                "name": "Export in RDF/XML",
                "url": "https://example.org/resource/xml",
                "format": "http://publications.europa.eu/resource/authority/file-type/RDF_XML",
            }
        ],
    }

    harvester._fix_resource_validation(package_dict)

    assert package_dict["resources"][0]["format"] == "RDF_XML"


def test_resource_validation_maps_iana_format_uri_to_file_type_code():
    harvester = CustomDcatHarvester()
    package_dict = {
        "name": "example",
        "resources": [
            {
                "name": "Export in RDF/XML",
                "url": "https://example.org/resource/xml",
                "format": "https://www.iana.org/assignments/media-types/application/rdf+xml",
            }
        ],
    }

    harvester._fix_resource_validation(package_dict)

    assert package_dict["resources"][0]["format"] == "RDF_XML"


def test_enrich_access_services_from_graph_adds_data_service_documentation():
    harvester = CustomDcatHarvester()
    service_uri = "https://data.gov.gr/dataset/example/resource/abc/access-service"
    graph = Graph()
    graph.parse(
        data=f"""<?xml version="1.0" encoding="utf-8"?>
        <rdf:RDF
          xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns:dcat="http://www.w3.org/ns/dcat#"
          xmlns:dct="http://purl.org/dc/terms/"
          xmlns:foaf="http://xmlns.com/foaf/0.1/">
          <dcat:Dataset rdf:about="https://data.gov.gr/dataset/example">
            <dcat:distribution>
              <dcat:Distribution rdf:about="https://data.gov.gr/resource/abc">
                <dcat:accessService rdf:resource="{service_uri}"/>
              </dcat:Distribution>
            </dcat:distribution>
          </dcat:Dataset>
          <dcat:DataService rdf:about="{service_uri}">
            <dct:title>Example API</dct:title>
            <dcat:endpointURL rdf:resource="https://data.gov.gr/api/action/datastore_search"/>
            <dcat:landingPage rdf:resource="https://data.gov.gr/docs/service"/>
            <foaf:page>
              <foaf:Document rdf:about="https://docs.ckan.org/en/2.11/maintaining/datastore.html#the-data-api"/>
            </foaf:page>
            <foaf:page>
              <foaf:Document rdf:about="https://data-gov-gr.gitbook.io/guides/texnika-egxeiridia/data.gov.gr/dedomena"/>
            </foaf:page>
          </dcat:DataService>
        </rdf:RDF>
        """,
        format="xml",
    )
    package_dict = {
        "resources": [
            {
                "access_services": json.dumps(
                    [
                        {
                            "uri": service_uri,
                            "access_service_ref": service_uri,
                            "endpoint_url": [
                                "https://data.gov.gr/api/action/datastore_search"
                            ],
                        }
                    ]
                )
            }
        ]
    }

    harvester._enrich_access_services_from_graph(package_dict, graph)

    access_services = json.loads(package_dict["resources"][0]["access_services"])
    assert access_services[0]["documentation"] == [
        "https://docs.ckan.org/en/2.11/maintaining/datastore.html#the-data-api",
        "https://data-gov-gr.gitbook.io/guides/texnika-egxeiridia/data.gov.gr/dedomena",
    ]
    assert access_services[0]["landing_page"] == ["https://data.gov.gr/docs/service"]


def test_build_data_service_dict_includes_documentation_fields():
    harvester = CustomDcatHarvester()
    ds_dict = harvester._build_data_service_dict(
        {
            "title": "Example API",
            "description": "Service description",
            "endpoint_url": "https://data.gov.gr/api/action/datastore_search",
            "endpoint_description": "Endpoint details",
            "documentation": [
                "https://docs.ckan.org/en/2.11/maintaining/datastore.html#the-data-api"
            ],
            "landing_page": "https://data.gov.gr/docs/service",
        },
        "example-ds-123",
        "org-id",
    )

    assert ds_dict["title"] == "Example API"
    assert ds_dict["notes"] == "Service description"
    assert ds_dict["endpoint_url"] == [
        "https://data.gov.gr/api/action/datastore_search"
    ]
    assert ds_dict["endpoint_description"] == ["Endpoint details"]
    assert ds_dict["documentation"] == [
        "https://docs.ckan.org/en/2.11/maintaining/datastore.html#the-data-api"
    ]
    assert ds_dict["landing_page"] == ["https://data.gov.gr/docs/service"]


def test_apply_data_service_harvested_fields_updates_existing_service():
    harvester = CustomDcatHarvester()
    existing = {
        "name": "example-ds-123",
        "title": "Old API",
        "notes": "Old description",
        "endpoint_url": ["https://old.example/api"],
        "documentation": ["https://old.example/docs"],
    }

    changed = harvester._apply_data_service_harvested_fields(
        existing,
        {
            "title": "New API",
            "description": "New description",
            "endpoint_url": ["https://new.example/api"],
            "documentation": ["https://new.example/docs"],
            "landing_page": ["https://new.example/service"],
        },
    )

    assert changed is True
    assert existing["title"] == "New API"
    assert existing["notes"] == "New description"
    assert existing["endpoint_url"] == ["https://new.example/api"]
    assert existing["documentation"] == ["https://new.example/docs"]
    assert existing["landing_page"] == ["https://new.example/service"]
