"""
Server-side καθαρισμός HTML για πεδία rich text (π.χ. περιγραφή dataset).

Εφαρμόζει πολιτική allowlist πάνω στο ``nh3`` (bindings της βιβλιοθήκης
ammonia), την ίδια βιβλιοθήκη που χρησιμοποιεί το CKAN από την 2.11.7:

- κρατά μόνο ασφαλή rich-text στοιχεία και attributes· αφαιρεί scripts,
  event handlers (``on*``) και επικίνδυνα στοιχεία/attributes· τα
  ``script``/``style`` κ.λπ. αφαιρούνται μαζί με το περιεχόμενό τους,
- επιτρέπει URLs μόνο με ``http``, ``https``, ``mailto``, ``tel`` ή σχετικά,
  άρα απορρίπτονται τα ``javascript:``, ``data:``, ``vbscript:`` κ.λπ.,
- κρατά μόνο CSS κλάσεις από allowlist, ώστε το περιεχόμενο να μη μπορεί να
  χρησιμοποιήσει κλάσεις τοποθέτησης του θέματος (π.χ. ``fixed-top``),
- κρατά inline ``style`` μόνο για ασφαλείς ιδιότητες και τιμές CSS,
- κρατά ``<iframe>`` μόνο με ``https`` src από τα εγκεκριμένα domains της
  ρύθμισης ``ckanext.data_gov_gr.html.iframe_allowed_domains`` και τους
  προσθέτει πάντα ``sandbox``, ``referrerpolicy`` και ``loading="lazy"``.

Χρησιμοποιείται με την ίδια πολιτική σε όλα τα σημεία απόδοσης της
περιγραφής (findings MSA-2026-002-012/013).
"""
import functools
import logging
import re
from urllib.parse import urlsplit

import nh3
from markupsafe import Markup, escape

import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)

IFRAME_ALLOWED_DOMAINS_CONFIG = 'ckanext.data_gov_gr.html.iframe_allowed_domains'
IFRAME_SANDBOX_CONFIG = 'ckanext.data_gov_gr.html.iframe_sandbox'
DEFAULT_IFRAME_ALLOWED_DOMAINS = 'geoportal.apdkritis.gov.gr opengov.thessaloniki.gr'
DEFAULT_IFRAME_SANDBOX = (
    'allow-scripts allow-same-origin allow-popups allow-forms '
    'allow-popups-to-escape-sandbox allow-downloads'
)
IFRAME_REFERRER_POLICY = 'strict-origin-when-cross-origin'

_TABLE_TAGS = frozenset([
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
    'colgroup', 'col',
])
_ALIGN_TAGS = ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')

ALLOWED_TAGS = frozenset([
    # Κείμενο και μπλοκ
    'p', 'br', 'hr', 'div', 'span', 'blockquote', 'pre', 'code', 'cite', 'q',
    # Μορφοποίηση
    'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup', 'font', 'small', 'mark',
    'del', 'ins', 'strike', 'kbd', 'abbr', 'acronym',
    # Επικεφαλίδες
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    # Λίστες
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    # Σύνδεσμοι, εικόνες, ενσωματώσεις
    'figure', 'figcaption', 'a', 'img', 'iframe',
]) | _TABLE_TAGS

# Στοιχεία που αφαιρούνται μαζί με το περιεχόμενό τους (όχι μόνο το tag),
# ώστε π.χ. κώδικας CSS/JS να μην εμφανίζεται ως κείμενο στη σελίδα.
CLEAN_CONTENT_TAGS = frozenset([
    'script', 'style', 'title', 'noscript', 'template', 'textarea',
])

_GLOBAL_ATTRIBUTES = frozenset(['title', 'lang', 'dir', 'style'])
_TABLE_ATTRIBUTES = frozenset([
    'border', 'cellpadding', 'cellspacing', 'align', 'width', 'valign',
    'colspan', 'rowspan', 'scope', 'span',
])
# Attributes ανά tag, μαζί με τα γενικά ('*'), όπως τα δέχεται το nh3
_ATTRIBUTES = {
    '*': _GLOBAL_ATTRIBUTES,
    # Το target επιτρέπεται μόνο με συγκεκριμένες τιμές (tag_attribute_values),
    # οπότε δεν μπαίνει εδώ. Τα rel και name ελέγχονται επιπλέον στο
    # attribute_filter (_LINK_REL_TOKENS, _ANCHOR_NAME_RE).
    'a': frozenset(['href', 'name', 'rel']),
    'img': frozenset(['src', 'alt', 'width', 'height']),
    'iframe': frozenset([
        'src', 'width', 'height', 'frameborder', 'scrolling', 'allowfullscreen',
    ]),
    'font': frozenset(['face', 'color', 'size']),
    'ol': frozenset(['start', 'type']),
    'ul': frozenset(['type']),
    'li': frozenset(['value']),
    **dict.fromkeys(_ALIGN_TAGS, frozenset(['align'])),
    **dict.fromkeys(_TABLE_TAGS, _TABLE_ATTRIBUTES),
}

# CSS κλάσεις που επιτρέπονται (όσες υπάρχουν στις περιγραφές και στο wrapper
# του template). Οι υπόλοιπες αφαιρούνται, ώστε να μη μπορούν να
# χρησιμοποιηθούν κλάσεις του Bootstrap που τοποθετούν περιεχόμενο πάνω από
# τη σελίδα (fixed-top, stretched-link κ.λπ.).
ALLOWED_CLASSES = frozenset([
    # Wrapper της περιγραφής στο package/read.html
    'notes', 'embedded-content',
    # Στοίχιση από rich text editors (Drupal RTE κ.λπ.)
    'rtejustify', 'rtecenter', 'rteright', 'rteleft',
    'text-align-justify', 'text-align-center', 'text-align-right', 'text-align-left',
    # Κουμπιά-σύνδεσμοι και πίνακες
    'btn', 'btn-primary', 'btn-default', 'btn-secondary',
    'table', 'Table', 'table-bordered', 'table-striped',
])

ALLOWED_PROTOCOLS = frozenset(['http', 'https', 'mailto', 'tel'])
_LINK_TARGETS = frozenset(['_blank', '_self'])
# Τιμές rel που κρατούνται (π.χ. το nofollow που βάζει το html_auto_link του
# CKAN). Το "opener" δεν επιτρέπεται: χωρίς αυτό οι browsers εφαρμόζουν
# noopener σε κάθε target="_blank".
_LINK_REL_TOKENS = frozenset([
    'nofollow', 'noopener', 'noreferrer', 'ugc', 'sponsored', 'external',
])

# Ιδιότητες CSS που επιτρέπονται σε inline style. Δεν επιτρέπονται ιδιότητες
# που αλλάζουν τη θέση/στρώση (position, z-index κ.λπ.) ούτε αρνητικές τιμές
# σε ιδιότητες που μετακινούν περιεχόμενο (_NO_NEGATIVE_CSS_PREFIXES). Αυτό
# περιορίζει, αλλά δεν αποκλείει, την κάλυψη στοιχείων της σελίδας (π.χ. με
# μεγάλο padding σε inline στοιχεία).
_ALLOWED_CSS_PROPERTIES = frozenset([
    'color', 'background', 'background-color',
    'line-height', 'letter-spacing', 'word-spacing', 'white-space',
    'text-align', 'text-indent', 'text-transform', 'vertical-align',
    'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
    'list-style-type', 'float', 'clear', 'box-sizing', 'table-layout',
    # Ακίνδυνες ιδιότητες που υπάρχουν σε κείμενο επικολλημένο από browsers/Word
    'orphans', 'widows', '-webkit-text-stroke-width',
])
# Ιδιότητες που επιτρέπονται μόνο με συγκεκριμένες τιμές
_CSS_KEYWORD_PROPERTIES = {
    'display': frozenset(['inline', 'inline-block', 'block']),
}
_ALLOWED_CSS_PREFIXES = ('margin', 'padding', 'border', 'font', 'text-decoration')
_FORBIDDEN_CSS_PREFIXES = ('border-image',)
_ALLOWED_CSS_FUNCTIONS = frozenset(['rgb', 'rgba', 'hsl', 'hsla'])
_CSS_PROPERTY_RE = re.compile(r'^-?[a-z][a-z-]*$')
# Χωρίς '*', '\\', '@', '<', ';' κ.λπ., άρα και χωρίς σχόλια CSS ή escapes
_CSS_VALUE_RE = re.compile(r'^[\w\s#%.,\'"()+\-/]*$', re.UNICODE)
# Και τα δύο ξεκινούν μόνο από αρχή λέξης ή από "!", ώστε ο χρόνος να μένει
# γραμμικός ακόμα και για πολύ μεγάλες τιμές (χωρίς ReDoS).
_CSS_FUNCTION_RE = re.compile(r'(?<![a-z-])([a-z-]+)\s*\(')
# Μόνο ASCII, όπως στο CSS (π.χ. το "!ımportant" μένει άκυρο).
_CSS_IMPORTANT_RE = re.compile(r'!\s*important$', re.IGNORECASE | re.ASCII)
# Σε αυτές τις ιδιότητες απορρίπτεται κάθε τιμή με "-": ο browser διαβάζει π.χ.
# το "0-500px" ως "0 -500px", οπότε δεν αρκεί έλεγχος μόνο για αρχικό "-".
_NO_NEGATIVE_CSS_PREFIXES = ('margin', 'text-indent', 'letter-spacing', 'word-spacing')

# Χαρακτήρες που δεν πρέπει να υπάρχουν σε src iframe (κενά, control, backslash).
_UNSAFE_URL_CHARS_RE = re.compile(r'[\s\\\x00-\x1f\x7f]')
_HOSTNAME_RE = re.compile(r'^[a-z0-9.-]+$')
# Άγκυρες υποσημειώσεων/περιεχομένων του Word (π.χ. _ftn1, _ftnref1, _Toc123).
# Μόνο αυτές επιτρέπονται ως name, ώστε να δουλεύουν τα links "#_ftn1" χωρίς
# να μπορεί το περιεχόμενο να ορίσει αυθαίρετα ονόματα (DOM clobbering).
_ANCHOR_NAME_RE = re.compile(r'^_(?:ftn|ftnref|edn|ednref|Toc)\d+$')

# Tag της εξόδου του nh3. Το nh3 γράφει πάντα τα attributes ως name="value"
# (με το " μέσα σε τιμή ως &quot;), αλλά ΔΕΝ κάνει escape τα < και > μέσα σε
# τιμές. Γι' αυτό η έξοδος διαβάζεται σειριακά από την αρχή (_finalize_iframes)
# και ποτέ με αναζήτηση "<iframe" σε τυχαία θέση.
_TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^\s"=>/]+="[^"]*")*)\s*/?>')
_ATTRIBUTE_NAME_RE = re.compile(r'\s+([^\s"=>/]+)="[^"]*"')
_IFRAME_END = '</iframe>'


def _sanitize_css(style):
    """
    Κρατά μόνο ασφαλείς δηλώσεις CSS από ένα ``style`` attribute.

    Το nh3 δίνει την τιμή ήδη αποκωδικοποιημένη (π.χ. &quot; -> "). Κρατά
    μόνο δηλώσεις με επιτρεπόμενη ιδιότητα και τιμή από ασφαλείς χαρακτήρες.
    Οι μόνες συναρτήσεις που επιτρέπονται είναι χρώματα (rgb/hsl), άρα
    απορρίπτονται ``url()``, ``expression()``, ``var()`` κ.λπ.
    """
    declarations = []
    for declaration in style.split(';'):
        if ':' not in declaration:
            continue
        prop, value = declaration.split(':', 1)
        prop = prop.strip().lower()
        value = value.strip()
        important = _CSS_IMPORTANT_RE.search(value)
        if important:
            value = value[:important.start()].rstrip()
        if not value:
            continue
        if prop in _CSS_KEYWORD_PROPERTIES:
            if value.lower() not in _CSS_KEYWORD_PROPERTIES[prop]:
                continue
        elif not _is_allowed_css_property(prop) or not _is_safe_css_value(value):
            continue
        # Αρνητικές τιμές μετακινούν το περιεχόμενο πάνω από στοιχεία της σελίδας
        if prop.startswith(_NO_NEGATIVE_CSS_PREFIXES) and '-' in value:
            continue
        declarations.append(
            '{}: {}{}'.format(prop, value, ' !important' if important else '')
        )
    return '; '.join(declarations)


def _is_allowed_css_property(prop):
    if not _CSS_PROPERTY_RE.match(prop):
        return False
    if prop.startswith(_FORBIDDEN_CSS_PREFIXES):
        return False
    return prop in _ALLOWED_CSS_PROPERTIES or prop.startswith(_ALLOWED_CSS_PREFIXES)


def _is_safe_css_value(value):
    if not _CSS_VALUE_RE.match(value):
        return False
    if value.count('(') != value.count(')'):
        return False
    functions = _CSS_FUNCTION_RE.findall(value.lower())
    if len(functions) != value.count('('):
        return False
    return all(name in _ALLOWED_CSS_FUNCTIONS for name in functions)


def _parse_host(entry):
    """Επιστρέφει το host ενός domain ή URL, χωρίς port και path."""
    entry = entry.strip().lower()
    if not entry:
        return ''
    if '://' not in entry:
        entry = '//' + entry
    try:
        host = urlsplit(entry).hostname or ''
    except ValueError:
        return ''
    return host.rstrip('.')


def _parse_allowed_domains(value):
    """
    Μετατρέπει τη ρύθμιση των εγκεκριμένων domains σε tuple από hosts.

    Δέχεται διαχωρισμό με κενά ή κόμματα. Από κάθε τιμή κρατείται μόνο το
    host (χωρίς scheme, port και path). Το ``*.example.gr`` σημαίνει μόνο
    subdomains. Μη έγκυρες τιμές αγνοούνται με warning στο log.
    """
    domains = []
    for entry in re.split(r'[\s,]+', value):
        if not entry:
            continue
        host = _parse_host(entry)
        if not host or not _HOSTNAME_RE.match(host.removeprefix('*.')):
            log.warning('Αγνοείται μη έγκυρο domain στο %s: %r',
                        IFRAME_ALLOWED_DOMAINS_CONFIG, entry)
            continue
        if host not in domains:
            domains.append(host)
    return tuple(domains)


def _host_is_allowed(host, allowed_domains):
    for domain in allowed_domains:
        if domain.startswith('*.'):
            if host.endswith(domain[1:]):
                return True
        elif host == domain:
            return True
    return False


def _is_portal_host(host, portal_domain):
    return bool(portal_domain) and (
        host == portal_domain or host.endswith('.' + portal_domain))


def _is_allowed_iframe_src(src, allowed_domains, portal_domain):
    """
    True μόνο για ``https`` URL στο default port, χωρίς userinfo, με host
    στα εγκεκριμένα domains και έξω από το domain του ίδιου του portal.
    """
    src = src.strip()
    if not src or _UNSAFE_URL_CHARS_RE.search(src):
        return False
    try:
        parts = urlsplit(src)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    # Το urlsplit επιστρέφει scheme και hostname ήδη σε πεζά
    if parts.scheme != 'https' or '@' in parts.netloc:
        return False
    if port not in (None, 443):
        return False
    if not host or not _HOSTNAME_RE.match(host):
        return False
    host = host.rstrip('.')
    # Iframe από το ίδιο origin με allow-scripts και allow-same-origin
    # μπορεί να αφαιρέσει το δικό του sandbox, οπότε δεν επιτρέπεται ποτέ.
    # Το portal μπορεί να σερβίρεται και από άλλο host του domain του (π.χ.
    # www.), άρα απορρίπτονται το domain του site_url και όλα τα subdomains του.
    if _is_portal_host(host, portal_domain):
        return False
    return _host_is_allowed(host, allowed_domains)


def _make_attribute_filter(allowed_domains, portal_domain):
    def attribute_filter(tag, attr, value):
        # Αν το φίλτρο σηκώσει οποιαδήποτε εξαίρεση (και BaseException, π.χ.
        # SystemExit), το nh3 την καταπίνει και κρατά την αρχική τιμή του
        # attribute, οπότε κάθε σφάλμα εδώ αφαιρεί το attribute.
        try:
            if attr == 'style':
                return _sanitize_css(value) or None
            if tag == 'iframe' and attr == 'src':
                if _is_allowed_iframe_src(value, allowed_domains, portal_domain):
                    return value
                return None
            if tag == 'a' and attr == 'name':
                return value if _ANCHOR_NAME_RE.match(value) else None
            if tag == 'a' and attr == 'rel':
                tokens = [t for t in value.lower().split() if t in _LINK_REL_TOKENS]
                return ' '.join(tokens) or None
            return value
        except BaseException:
            log.exception('Σφάλμα στον έλεγχο του %s@%s· το attribute αφαιρείται.',
                          tag, attr)
            return None
    return attribute_filter


@functools.lru_cache(maxsize=16)
def _build_cleaner(raw_domains, raw_sandbox, site_url):
    """
    Φτιάχνει τον ``nh3.Cleaner`` για συγκεκριμένες ρυθμίσεις.

    Κρατείται σε cache με κλειδί τις ρυθμίσεις, ώστε η πολιτική να χτίζεται
    μία φορά. Το ``nh3`` δεν κρατά κατάσταση ανά κλήση, άρα ο ίδιος Cleaner
    μπορεί να χρησιμοποιείται από όλα τα threads/greenlets.
    """
    allowed_domains = _parse_allowed_domains(raw_domains)
    portal_domain = _parse_host(site_url).removeprefix('www.')
    for domain in allowed_domains:
        if (_is_portal_host(domain.removeprefix('*.'), portal_domain)
                or _host_is_allowed(portal_domain, (domain,))):
            log.warning(
                'Το %r στο %s επικαλύπτεται με το domain του portal· iframe από '
                'το %s και τα subdomains του απορρίπτονται πάντα.',
                domain, IFRAME_ALLOWED_DOMAINS_CONFIG, portal_domain)

    return nh3.Cleaner(
        tags=ALLOWED_TAGS,
        clean_content_tags=CLEAN_CONTENT_TAGS,
        attributes=_ATTRIBUTES,
        attribute_filter=_make_attribute_filter(allowed_domains, portal_domain),
        strip_comments=True,
        # Το rel του περιεχομένου κρατείται φιλτραρισμένο (attribute_filter)·
        # το nh3 δεν το αντικαθιστά, ώστε να μένει το nofollow του CKAN και να
        # μην μπαίνει noreferrer στα εσωτερικά links (Matomo).
        link_rel=None,
        url_schemes=ALLOWED_PROTOCOLS,
        allowed_classes=dict.fromkeys(ALLOWED_TAGS, ALLOWED_CLASSES),
        tag_attribute_values={'a': {'target': _LINK_TARGETS}},
        set_tag_attribute_values={'iframe': {
            'sandbox': ' '.join(raw_sandbox.split()),
            'referrerpolicy': IFRAME_REFERRER_POLICY,
            'loading': 'lazy',
        }},
    )


def _get_cleaner():
    # Τα defaults γράφονται στο config από τις δηλώσεις του plugin
    # (declare_config_options). Χωρίς φορτωμένο config, το κενό σημαίνει
    # κανένα iframe και τον αυστηρότερο sandbox.
    config = toolkit.config
    return _build_cleaner(
        config.get(IFRAME_ALLOWED_DOMAINS_CONFIG) or '',
        config.get(IFRAME_SANDBOX_CONFIG) or '',
        config.get('ckan.site_url') or '',
    )


def _finalize_iframes(html):
    """
    Αφαιρεί ολόκληρα τα iframe χωρίς εγκεκριμένο src και το περιεχόμενο
    όσων μένουν.

    Το nh3 αφαιρεί μόνο το src ενός μη εγκεκριμένου iframe και θα έμενε ένα
    κενό πλαίσιο. Η έξοδος του nh3 διαβάζεται σειριακά, tag προς tag: το <
    στο κείμενο είναι πάντα &lt;, οπότε κάθε < που συναντάμε έξω από tag είναι
    αρχή πραγματικού tag, ενώ ένα "<iframe" μέσα σε τιμή attribute
    καταναλώνεται μαζί με το tag του. Το περιεχόμενο ενός iframe είναι raw
    text μέχρι το πρώτο </iframe>. Ο χρόνος είναι γραμμικός.
    """
    if '<iframe' not in html:
        return html
    out = []
    pos = 0
    while True:
        start = html.find('<', pos)
        if start == -1:
            out.append(html[pos:])
            break
        out.append(html[pos:start])
        tag = _TAG_RE.match(html, start)
        if tag is None:
            # Δεν αναμένεται σε έξοδο του nh3 (π.χ. αλλαγή μορφής σε νέα έκδοση).
            # Αφού δεν ξέρουμε πού τελειώνει το tag, όλο το υπόλοιπο γίνεται
            # κείμενο, ώστε τίποτα από μέσα του να μην αποδοθεί ως HTML.
            log.warning('Μη αναμενόμενη έξοδος nh3 στη θέση %d· το υπόλοιπο '
                        'της περιγραφής εμφανίζεται ως κείμενο.', start)
            out.append(str(escape(html[start:])))
            break
        if tag.group(2).lower() != 'iframe':
            out.append(tag.group(0))
            pos = tag.end()
            continue
        if tag.group(1):
            # Κλείσιμο iframe χωρίς άνοιγμα· παραλείπεται
            pos = tag.end()
            continue
        end = html.find(_IFRAME_END, tag.end())
        pos = len(html) if end == -1 else end + len(_IFRAME_END)
        if 'src' in _ATTRIBUTE_NAME_RE.findall(tag.group(3)):
            # Το περιεχόμενο ενός iframe δεν εμφανίζεται ποτέ· παραλείπεται
            out.append(tag.group(0) + _IFRAME_END)
    return ''.join(out)


def sanitize_html(value):
    """
    Καθαρίζει HTML με την πολιτική allowlist και επιστρέφει ``Markup``.

    Το αποτέλεσμα μπορεί να εμφανιστεί απευθείας στο template χωρίς
    ``|safe``. Τιμές που δεν είναι string μετατρέπονται πρώτα σε κείμενο.
    """
    value = '' if value is None else str(value)
    if not value.strip():
        return Markup('')
    return Markup(_finalize_iframes(_get_cleaner().clean(value)))
