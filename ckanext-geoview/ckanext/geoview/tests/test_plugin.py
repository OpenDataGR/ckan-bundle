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


def test_service_proxy_network_defaults(monkeypatch):
    keys = (
        "ckanext.geoview.service_proxy.connect_timeout",
        "ckanext.geoview.service_proxy.read_timeout",
        "ckanext.geoview.service_proxy.max_redirects",
    )
    for key in keys:
        monkeypatch.delitem(utils.toolkit.config, key, raising=False)

    assert utils.get_service_proxy_connect_timeout() == 10
    assert utils.get_service_proxy_read_timeout() == 90
    assert utils.get_service_proxy_max_redirects() == 10


def test_service_proxy_network_config_is_read_and_capped(monkeypatch):
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.connect_timeout",
        "999",
    )
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.read_timeout",
        "999",
    )
    monkeypatch.setitem(
        utils.toolkit.config,
        "ckanext.geoview.service_proxy.max_redirects",
        "999",
    )

    assert utils.get_service_proxy_connect_timeout() == 60
    assert utils.get_service_proxy_read_timeout() == 300
    assert utils.get_service_proxy_max_redirects() == 20
