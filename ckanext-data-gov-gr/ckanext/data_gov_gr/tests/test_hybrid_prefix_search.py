import pytest

from ckan.tests import factories, helpers as test_helpers

from ckanext.data_gov_gr import helpers
from ckanext.data_gov_gr import plugin as plugin_module
from ckanext.data_gov_gr.plugin import (
    DataGovGrPlugin,
    HYBRID_PREFIX_LIVE_SEARCH_CONFIG,
    HYBRID_PREFIX_LIVE_SEARCH_PARAM,
    HYBRID_PREFIX_SEARCH_CONFIG,
    build_hybrid_prefix_query,
)


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "data_gov_gr"),
    pytest.mark.usefixtures("with_plugins"),
]


def _config_enabled(monkeypatch, *enabled_keys):
    monkeypatch.setattr(
        helpers,
        "get_config_as_bool",
        lambda key, default=False: key in enabled_keys,
    )


def test_builds_low_boost_prefix_fallback_for_simple_word():
    assert build_hybrid_prefix_query("  μετεωρ  ") == (
        "(μετεωρ)^5 OR (text:μετεωρ*)^0.2"
    )


@pytest.mark.parametrize(
    "query",
    [None, "", "abc", "δύο λέξεις", "μετεωρ*", "title:μετεωρ"],
)
def test_does_not_rewrite_short_or_advanced_queries(query):
    assert build_hybrid_prefix_query(query) is None


def test_applies_to_main_search_when_main_option_is_enabled(monkeypatch):
    plugin = DataGovGrPlugin()
    monkeypatch.setattr(plugin, "_is_supported_search_endpoint", lambda: True)
    _config_enabled(monkeypatch, HYBRID_PREFIX_SEARCH_CONFIG)
    search = {"q": "μετεωρ", "extras": {}}

    plugin._apply_hybrid_prefix_search(search)

    assert search["q"] == "(μετεωρ)^5 OR (text:μετεωρ*)^0.2"
    assert search["defType"] == "edismax"
    assert search["mm"] == "1"


def test_live_search_has_an_independent_option(monkeypatch):
    plugin = DataGovGrPlugin()
    monkeypatch.setattr(plugin, "_is_supported_search_endpoint", lambda: False)
    _config_enabled(monkeypatch, HYBRID_PREFIX_LIVE_SEARCH_CONFIG)
    search = {
        "q": "μετεωρ",
        "extras": {HYBRID_PREFIX_LIVE_SEARCH_PARAM: True},
    }

    plugin._apply_hybrid_prefix_search(search)

    assert search["q"] == "(μετεωρ)^5 OR (text:μετεωρ*)^0.2"
    assert search["defType"] == "edismax"
    assert search["mm"] == "1"
    assert HYBRID_PREFIX_LIVE_SEARCH_PARAM not in search["extras"]


def test_live_marker_is_removed_when_feature_is_disabled(monkeypatch):
    plugin = DataGovGrPlugin()
    monkeypatch.setattr(plugin, "_is_supported_search_endpoint", lambda: False)
    _config_enabled(monkeypatch)
    search = {
        "q": "μετεωρ",
        "extras": {HYBRID_PREFIX_LIVE_SEARCH_PARAM: True},
    }

    plugin._apply_hybrid_prefix_search(search)

    assert search["q"] == "μετεωρ"
    assert "defType" not in search
    assert HYBRID_PREFIX_LIVE_SEARCH_PARAM not in search["extras"]


@pytest.mark.parametrize(
    ("option", "value"),
    [("defType", "lucene"), ("qf", "title"), ("mm", "100%")],
)
def test_leaves_explicit_solr_query_options_untouched(
    monkeypatch,
    option,
    value,
):
    plugin = DataGovGrPlugin()
    monkeypatch.setattr(plugin, "_is_supported_search_endpoint", lambda: True)
    _config_enabled(monkeypatch, HYBRID_PREFIX_SEARCH_CONFIG)
    search = {"q": "μετεωρ", option: value, "extras": {}}

    plugin._apply_hybrid_prefix_search(search)

    assert search == {"q": "μετεωρ", option: value, "extras": {}}


def test_does_not_change_unrelated_package_search_calls(monkeypatch):
    plugin = DataGovGrPlugin()
    monkeypatch.setattr(plugin, "_is_supported_search_endpoint", lambda: False)
    _config_enabled(
        monkeypatch,
        HYBRID_PREFIX_SEARCH_CONFIG,
        HYBRID_PREFIX_LIVE_SEARCH_CONFIG,
    )
    search = {"q": "μετεωρ", "extras": {}}

    plugin._apply_hybrid_prefix_search(search)

    assert search == {"q": "μετεωρ", "extras": {}}


@pytest.mark.ckan_config(HYBRID_PREFIX_LIVE_SEARCH_CONFIG, True)
@pytest.mark.usefixtures("clean_db", "clean_index")
def test_prefix_fallback_runs_through_package_search_and_solr(monkeypatch):
    assert helpers.get_config_as_bool(
        HYBRID_PREFIX_LIVE_SEARCH_CONFIG,
        default=False,
    ) is True

    factories.Dataset(
        name="meteorological-data",
        title="Meteorological observations",
    )
    factories.Dataset(
        name="exact-meteo-data",
        title="Meteo observations",
    )

    baseline = test_helpers.call_action(
        "package_search",
        q="meteorological",
    )
    assert [item["name"] for item in baseline["results"]] == [
        "meteorological-data"
    ]

    rewritten_queries = []
    original_builder = plugin_module.build_hybrid_prefix_query

    def record_rewrite(query):
        rewritten_queries.append(query)
        return original_builder(query)

    monkeypatch.setattr(
        plugin_module,
        "build_hybrid_prefix_query",
        record_rewrite,
    )
    result = test_helpers.call_action(
        "package_search",
        q="meteo",
        **{HYBRID_PREFIX_LIVE_SEARCH_PARAM: True},
    )

    assert rewritten_queries == ["meteo"]
    assert [item["name"] for item in result["results"]] == [
        "exact-meteo-data",
        "meteorological-data",
    ]
