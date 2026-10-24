from pathlib import Path

from babel.support import Translations


I18N_DIR = Path(__file__).parents[1] / "i18n"
TEMPLATE = (
    Path(__file__).parents[1]
    / "templates"
    / "hvd_validator"
    / "validate.html"
)


def _greek_translations():
    return Translations.load(
        I18N_DIR,
        locales=["el"],
        domain="ckanext-hvd_validator",
    )


def test_open_license_status_uses_contextual_translation():
    translations = _greek_translations()

    assert translations.pgettext("license status", "Open") == "Ανοικτή"


def test_hvd_catalog_does_not_override_generic_open_translation():
    translations = _greek_translations()

    assert translations.gettext("Open") == "Open"


def test_license_status_template_uses_translation_context():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "pgettext('license status', 'Open')" in source
    assert "{{ _('Open') }}" not in source
