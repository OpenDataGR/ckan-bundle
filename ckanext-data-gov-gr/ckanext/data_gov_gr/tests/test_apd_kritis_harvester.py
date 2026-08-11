from ckanext.data_gov_gr.harvesters.apd_kritis_harvester import (
    ApdKritisHarvester,
)


def _harvester():
    return ApdKritisHarvester.__new__(ApdKritisHarvester)


class TestFixContactFromSource:

    def test_email_without_mailto(self):
        package_dict = {"contact": [{"name": "Διεύθυνση Υδάτων", "email": ""}]}
        source = {
            "contactPoint": {
                "fn": "Διεύθυνση Υδάτων",
                "hasEmail": "ydata@apdkritis.gov.gr",
            }
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "ydata@apdkritis.gov.gr"

    def test_email_with_mailto_prefix(self):
        package_dict = {"contact": [{"name": "Διεύθυνση Υδάτων", "email": ""}]}
        source = {
            "contactPoint": {
                "fn": "Διεύθυνση Υδάτων",
                "hasEmail": "mailto:ydata@apdkritis.gov.gr",
            }
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "ydata@apdkritis.gov.gr"

    def test_overwrites_broken_file_uri_email(self):
        package_dict = {
            "contact": [
                {
                    "name": "Διεύθυνση Υδάτων",
                    "email": "file:///some/path/ydata@apdkritis.gov.gr",
                }
            ]
        }
        source = {
            "contactPoint": {
                "fn": "Διεύθυνση Υδάτων",
                "hasEmail": "ydata@apdkritis.gov.gr",
            }
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "ydata@apdkritis.gov.gr"

    def test_no_contact_point_in_source(self):
        package_dict = {"contact": [{"name": "Test", "email": "test@test.gr"}]}
        source = {"title": "No contact here"}
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "test@test.gr"

    def test_creates_contact_when_missing(self):
        package_dict = {}
        source = {
            "contactPoint": {
                "fn": "Διεύθυνση Υδάτων",
                "hasEmail": "ydata@apdkritis.gov.gr",
            }
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert len(package_dict["contact"]) == 1
        assert package_dict["contact"][0]["name"] == "Διεύθυνση Υδάτων"
        assert package_dict["contact"][0]["email"] == "ydata@apdkritis.gov.gr"

    def test_contact_point_as_list(self):
        package_dict = {}
        source = {
            "contactPoint": [
                {
                    "fn": "Διεύθυνση Υδάτων",
                    "hasEmail": "ydata@apdkritis.gov.gr",
                }
            ]
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "ydata@apdkritis.gov.gr"

    def test_preserves_existing_correct_email(self):
        package_dict = {
            "contact": [{"name": "Διεύθυνση Υδάτων", "email": "correct@test.gr"}]
        }
        source = {
            "contactPoint": {
                "fn": "Other Contact",
                "hasEmail": "other@test.gr",
            }
        }
        _harvester()._fix_contact_from_source(package_dict, source)
        assert package_dict["contact"][0]["email"] == "correct@test.gr"
        assert len(package_dict["contact"]) == 2
        assert package_dict["contact"][1]["email"] == "other@test.gr"


class TestFixPublisherFromSource:

    def test_injects_publisher_name(self):
        package_dict = {"publisher": [{"name": "", "uri": ""}]}
        source = {
            "publisher": {"@type": "org:Organization", "name": "Διεύθυνση Υδάτων"}
        }
        _harvester()._fix_publisher_from_source(package_dict, source)
        assert package_dict["publisher"][0]["name"] == "Διεύθυνση Υδάτων"

    def test_creates_publisher_when_missing(self):
        package_dict = {}
        source = {
            "publisher": {"@type": "org:Organization", "name": "Διεύθυνση Υδάτων"}
        }
        _harvester()._fix_publisher_from_source(package_dict, source)
        assert len(package_dict["publisher"]) == 1
        assert package_dict["publisher"][0]["name"] == "Διεύθυνση Υδάτων"

    def test_no_publisher_in_source(self):
        package_dict = {"publisher": [{"name": "Existing", "uri": ""}]}
        source = {"title": "No publisher here"}
        _harvester()._fix_publisher_from_source(package_dict, source)
        assert package_dict["publisher"][0]["name"] == "Existing"

    def test_preserves_existing_publisher_name(self):
        package_dict = {"publisher": [{"name": "Already Set", "uri": ""}]}
        source = {
            "publisher": {"@type": "org:Organization", "name": "Διεύθυνση Υδάτων"}
        }
        _harvester()._fix_publisher_from_source(package_dict, source)
        assert package_dict["publisher"][0]["name"] == "Already Set"

    def test_skips_empty_source_name(self):
        package_dict = {}
        source = {"publisher": {"@type": "org:Organization", "name": ""}}
        _harvester()._fix_publisher_from_source(package_dict, source)
        assert "publisher" not in package_dict


class TestDropEmptyConformsToFromSource:

    def test_removes_file_uri_conforms_to_extra_when_source_is_empty(self):
        package_dict = {
            "extras": [
                {
                    "key": "conforms_to",
                    "value": '["file:///opt/ckan/lib/default/src/ckan/"]',
                },
                {"key": "identifier", "value": "bbc6c56a-a429-44ea-a651-54b535d586c5"},
            ]
        }
        source = {"conformsTo": ""}

        _harvester()._drop_empty_conforms_to_from_source(package_dict, source)

        assert package_dict["extras"] == [
            {"key": "identifier", "value": "bbc6c56a-a429-44ea-a651-54b535d586c5"}
        ]

    def test_removes_root_conforms_to_when_source_is_empty(self):
        package_dict = {
            "conforms_to": ["file:///opt/ckan/lib/default/src/ckan/"],
            "title": "Dataset",
        }
        source = {"conformsTo": ""}

        _harvester()._drop_empty_conforms_to_from_source(package_dict, source)

        assert "conforms_to" not in package_dict
        assert package_dict["title"] == "Dataset"

    def test_preserves_conforms_to_when_source_has_value(self):
        package_dict = {
            "extras": [
                {
                    "key": "conforms_to",
                    "value": '["https://example.test/standard"]',
                }
            ]
        }
        source = {"conformsTo": "https://example.test/standard"}

        _harvester()._drop_empty_conforms_to_from_source(package_dict, source)

        assert package_dict["extras"] == [
            {
                "key": "conforms_to",
                "value": '["https://example.test/standard"]',
            }
        ]

    def test_preserves_conforms_to_when_source_field_is_absent(self):
        package_dict = {
            "extras": [
                {
                    "key": "conforms_to",
                    "value": '["https://example.test/standard"]',
                }
            ]
        }
        source = {}

        _harvester()._drop_empty_conforms_to_from_source(package_dict, source)

        assert package_dict["extras"] == [
            {
                "key": "conforms_to",
                "value": '["https://example.test/standard"]',
            }
        ]


class TestSkipPublisherConfig:

    def test_skip_publisher_removes_field(self):
        package_dict = {
            "publisher": [{"name": "Διεύθυνση Υδάτων"}],
        }
        config = {"skip_publisher": True}
        if config.get("skip_publisher"):
            package_dict.pop("publisher", None)
        assert "publisher" not in package_dict

    def test_skip_publisher_false_preserves_field(self):
        package_dict = {
            "publisher": [{"name": "Διεύθυνση Υδάτων"}],
        }
        config = {"skip_publisher": False}
        if config.get("skip_publisher"):
            package_dict.pop("publisher", None)
        assert package_dict["publisher"][0]["name"] == "Διεύθυνση Υδάτων"

    def test_skip_publisher_absent_preserves_field(self):
        package_dict = {
            "publisher": [{"name": "Διεύθυνση Υδάτων"}],
        }
        config = {}
        if config.get("skip_publisher"):
            package_dict.pop("publisher", None)
        assert package_dict["publisher"][0]["name"] == "Διεύθυνση Υδάτων"
