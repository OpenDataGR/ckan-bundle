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
