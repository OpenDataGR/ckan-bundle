from ckanext.geoview import plugin
from ckanext.geoview import utils


def test_plugin():
    """This is here just as a sanity test
    """
    p = plugin.OLGeoView()
    assert p


def test_service_proxy_max_file_size_defaults_to_three_mb(monkeypatch):
    monkeypatch.delitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.max_file_size_mb",
        raising=False,
    )

    assert utils.get_service_proxy_max_file_size() == 3 * 1024 * 1024


def test_service_proxy_max_file_size_reads_mb_config(monkeypatch):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.max_file_size_mb",
        "10",
    )

    assert utils.get_service_proxy_max_file_size() == 10 * 1024 * 1024


def test_service_proxy_max_file_size_ignores_invalid_config(monkeypatch):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.max_file_size_mb",
        "0",
    )

    assert utils.get_service_proxy_max_file_size() == 3 * 1024 * 1024
