from ckanext.data_gov_gr.harvesters.attica_harvester import (
    AtticaOpenDataHarvester,
)


def _harvester():
    return AtticaOpenDataHarvester.__new__(AtticaOpenDataHarvester)


def _tag_names(dataset_data, include_creator_names=True):
    package_dict = {}
    harvester = _harvester()

    harvester._attach_tags(
        package_dict,
        dataset_data,
        include_creator_names=include_creator_names,
    )

    return [tag["name"] for tag in package_dict["tags"]]


def test_attach_tags_adds_creator_names():
    tag_names = _tag_names(
        {
            "creator": [
                {"name": "Γενική Διεύθυνση Ανάπτυξης"},
                {"name": "Διεύθυνση Εμπορίου"},
            ]
        }
    )

    assert "Γενική Διεύθυνση Ανάπτυξης" in tag_names
    assert "Διεύθυνση Εμπορίου" in tag_names


def test_attach_tags_skips_creator_without_name():
    tag_names = _tag_names(
        {
            "creator": [
                {"identifier": "general-directorate"},
                None,
            ]
        }
    )

    assert tag_names == ["Περιφέρεια Αττικής", "Ανοικτά Δεδομένα"]


def test_attach_tags_cleans_and_deduplicates_creator_names():
    tag_names = _tag_names(
        {
            "tags": ["Διεύθυνση Εμπορίου"],
            "creator": [
                {"name": "διεύθυνση εμπορίου"},
                {"name": "Γενική Διεύθυνση / Ανάπτυξης"},
            ],
        }
    )

    assert tag_names.count("Διεύθυνση Εμπορίου") == 1
    assert "διεύθυνση εμπορίου" not in tag_names
    assert "Γενική Διεύθυνση - Ανάπτυξης" in tag_names


def test_attach_tags_can_exclude_creator_names():
    tag_names = _tag_names(
        {
            "creator": [
                {"name": "Γενική Διεύθυνση Ανάπτυξης"},
            ]
        },
        include_creator_names=False,
    )

    assert "Γενική Διεύθυνση Ανάπτυξης" not in tag_names
    assert tag_names == ["Περιφέρεια Αττικής", "Ανοικτά Δεδομένα"]


def test_convert_to_ckan_package_includes_creator_names_by_default(monkeypatch):
    harvester = _harvester()
    monkeypatch.setattr(harvester, "_build_base_package", lambda data: {})
    monkeypatch.setattr(harvester, "_apply_translated_fields", lambda package: None)
    monkeypatch.setattr(harvester, "_build_extras", lambda data: [])
    monkeypatch.setattr(harvester, "_apply_dcat_fields", lambda package, data: None)
    monkeypatch.setattr(
        harvester,
        "_attach_resources",
        lambda package, data, license_id: None,
    )
    monkeypatch.setattr(
        harvester,
        "_compute_portal_categories_theme_and_tags",
        lambda data: (set(), []),
    )
    dataset_data = {
        "creator": [{"name": "Διεύθυνση Εμπορίου"}],
    }

    package_dict = harvester._convert_to_ckan_package(dataset_data)

    assert {"name": "Διεύθυνση Εμπορίου"} in package_dict["tags"]


def test_convert_to_ckan_package_can_disable_creator_name_tags(monkeypatch):
    harvester = _harvester()
    monkeypatch.setattr(harvester, "_build_base_package", lambda data: {})
    monkeypatch.setattr(harvester, "_apply_translated_fields", lambda package: None)
    monkeypatch.setattr(harvester, "_build_extras", lambda data: [])
    monkeypatch.setattr(harvester, "_apply_dcat_fields", lambda package, data: None)
    monkeypatch.setattr(
        harvester,
        "_attach_resources",
        lambda package, data, license_id: None,
    )
    monkeypatch.setattr(
        harvester,
        "_compute_portal_categories_theme_and_tags",
        lambda data: (set(), []),
    )
    dataset_data = {
        "creator": [{"name": "Διεύθυνση Εμπορίου"}],
    }

    package_dict = harvester._convert_to_ckan_package(
        dataset_data,
        source_config={"include_creator_names_as_tags": "false"},
    )

    assert {"name": "Διεύθυνση Εμπορίου"} not in package_dict["tags"]
    assert dataset_data["creator"] == [{"name": "Διεύθυνση Εμπορίου"}]


def test_bool_value_parses_creator_tag_config_values():
    harvester = _harvester()

    assert harvester._bool_value(None, True) is True
    assert harvester._bool_value(True, False) is True
    assert harvester._bool_value(False, True) is False
    assert harvester._bool_value("true", False) is True
    assert harvester._bool_value("false", True) is False
