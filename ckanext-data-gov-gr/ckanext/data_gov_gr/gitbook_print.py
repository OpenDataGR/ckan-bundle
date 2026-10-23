# -*- coding: utf-8 -*-
"""
Σελίδα εκτύπωσης (λήψη PDF μέσω browser) για τους οδηγούς του GitBook.

Οι σελίδες επιλέγονται όπως στο PDF export του GitBook: όλες οι ορατές
σελίδες του space, ή μία σελίδα μαζί με τις ορατές υποσελίδες της.

- δομή και τίτλος από το GitBook API (``/spaces/{id}``, ``content/pages``)
- περιεχόμενο από το δημόσιο ``{guides_base_url}/llms-full.txt``
- όσες σελίδες λείπουν από εκεί, από ``content/page/{page_id}?format=markdown``
"""
import copy
import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html import escape, unescape
from urllib.parse import quote, urljoin, urlparse

import bleach
import markdown
import requests
from markdown.extensions.toc import slugify_unicode

from ckan.common import config
from ckan.lib.helpers import MARKDOWN_ATTRIBUTES, MARKDOWN_TAGS

log = logging.getLogger(__name__)

GITBOOK_SPACE_ENDPOINT = 'https://api.gitbook.com/v1/spaces/{space_id}'
GITBOOK_SPACE_PAGES_ENDPOINT = 'https://api.gitbook.com/v1/spaces/{space_id}/content/pages'
GITBOOK_PAGE_CONTENT_ENDPOINT = (
    'https://api.gitbook.com/v1/spaces/{space_id}/content/page/{page_id}'
)
REQUEST_TIMEOUT = 60
# Παράλληλες κλήσεις στο API για σελίδες που λείπουν από το llms-full.txt
MISSING_PAGE_WORKERS = 6
# Πεδία σελίδας που κρατάμε από το content/pages
PAGE_FIELDS = ('id', 'title', 'slug', 'description', 'type', 'path', 'hidden', 'noIndex')
# Όριο ασφαλείας για τα κομμάτια του llms-full.txt (100 σελίδες ανά κομμάτι)
LLMS_FULL_MAX_PARTS = 20
CACHE_TTL_KEY = 'ckanext.data_gov_gr.gitbook.pages_cache_ttl'
SETTINGS_KEYS = (
    'ckanext.data_gov_gr.gitbook.space_id',
    'ckanext.data_gov_gr.gitbook.api_token',
    'guides_base_url',
)
CACHE_TTL_DEFAULT = 86400

PRINT_TAGS = set(MARKDOWN_TAGS) | {
    'h4', 'h5', 'h6', 'div', 'span', 'figure', 'figcaption', 'details',
    'summary', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'caption', 'mark', 'u', 'small',
}
PRINT_ATTRIBUTES = copy.deepcopy(MARKDOWN_ATTRIBUTES)
PRINT_ATTRIBUTES.setdefault('*', []).extend(['id', 'class'])
PRINT_ATTRIBUTES.setdefault('img', []).extend(['width', 'height', 'data-size'])
PRINT_ATTRIBUTES['details'] = ['open']
PRINT_ATTRIBUTES['th'] = ['colspan', 'rowspan', 'align']
PRINT_ATTRIBUTES['td'] = ['colspan', 'rowspan', 'align']

_LLMS_HEADER_START_RE = re.compile(r'^>\s*This is part \d+', re.I)
_LLMS_NEXT_PART_RE = re.compile(r'^>\s*Next part:\s*(\S+)\s*$', re.M)
# Υποσέλιδο κάθε κομματιού: «---» και link «Next Page» προς το επόμενο κομμάτι
_LLMS_FOOTER_RE = re.compile(r'\n\s*---\s*\n\s*\[[^\]]*\]\([^)]*llms-full\.txt[^)]*\)\s*\Z')
_INLINE_CODE_RE = re.compile(r'(`+)(.+?)\1')
# Escapes του GitBook που δεν αναγνωρίζει το Python-Markdown
_GITBOOK_ESCAPES = {'&': '&amp;', '<': '&lt;', ':': ':'}
_GITBOOK_ESCAPE_RE = re.compile(r'\\([&<:])')
_BACKSLASH_BEFORE_BR_RE = re.compile(r'\\\s+(?=<br\s*/?>)')
_AUTOLINK_RE = re.compile(r'<(https?://[^>\s]+)>')
_FRONT_MATTER_RE = re.compile(r'\A---\s*\n.*?\n---\s*\n', re.S)
_FENCE_RE = re.compile(r'^\s*(```|~~~)')
_LIQUID_TAG_RE = re.compile(r'\{%-?\s*([a-z][a-z-]*)((?:[^%]|%(?!\}))*?)-?%\}')
_LIQUID_ARG_RE = re.compile(r'([a-z][a-z-]*)="([^"]*)"')
_DETAILS_OPEN_RE = re.compile(r'<details\b[^>]*>')
_CARDS_TABLE_RE = re.compile(
    r'<table\b[^>]*data-view="cards"[^>]*>(.*?)</table>', re.S
)
_TH_RE = re.compile(r'<th\b([^>]*)>', re.S)
_TR_RE = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S)
_TD_RE = re.compile(r'<td\b[^>]*>(.*?)</td>', re.S)
_HREF_RE = re.compile(r'\bhref="([^"]*)"')
_URL_ATTR_RE = re.compile(r'\b(href|src)="([^"]*)"')
# Μόνο μέσα σε πραγματικά tags (όχι σε κείμενο <code>, που είναι ήδη &lt;…)
_TAG_URL_ATTR_RE = re.compile(r'(<(?:a|img)\b[^>]*?\s)(href|src)="([^"]*)"')
_MD_ESCAPE_RE = re.compile(r'\\([!-/:-@\[-`{-~])')
_MD_LINK_RE = re.compile(r'(\]\()([^)\s]+)')
_H1_RE = re.compile(r'^# (.+?)\s*$')


def get_settings():
    """
    ``(space_id, token, guides_base_url)`` αν είναι όλα ρυθμισμένα, αλλιώς ``None``.

    Χρειάζονται και τα τρία: δομή από το API, περιεχόμενο από το
    ``{guides_base_url}/llms-full.txt``.
    """
    values = tuple((config.get(key) or '').strip() for key in SETTINGS_KEYS)
    return values if all(values) else None


def get_cached(key_suffix, producer):
    """
    Επιστρέφει την τιμή από τη Redis ή την παράγει με ``producer()``.

    Η τιμή αποθηκεύεται ως JSON με TTL από το
    ``ckanext.data_gov_gr.gitbook.pages_cache_ttl``. Το ``None`` (αποτυχία)
    δεν αποθηκεύεται ποτέ, ώστε η επόμενη κλήση να ξαναδοκιμάσει.
    """
    cache_ttl = int(config.get(CACHE_TTL_KEY, CACHE_TTL_DEFAULT) or 0)
    site_id = (config.get('ckan.site_id') or 'default').strip()
    redis_key = f'ckan:{site_id}:ckanext:data_gov_gr:{key_suffix}'
    redis_conn = None

    try:
        from ckan.lib.redis import connect_to_redis
        redis_conn = connect_to_redis()
        cached = redis_conn.get(redis_key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        log.debug('Redis cache read failed for %s: %s', key_suffix, exc)

    value = producer()
    if value is None:
        return None

    if redis_conn and cache_ttl > 0:
        try:
            redis_conn.setex(redis_key, cache_ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            log.debug('Redis cache write failed for %s: %s', key_suffix, exc)

    return value


def _http_get(url, **kwargs):
    """GET με timeout· επιστρέφει την απάντηση ή ``None`` (με log) σε σφάλμα ή HTTP >= 400."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        log.error('GitBook request failed (%s): %s', url, exc)
        return None

    if resp.status_code >= 400:
        log.error('GitBook request failed (%s) %s: %s', resp.status_code, url, resp.text[:500])
        return None
    return resp


def _split_llms_header(text):
    """
    Χωρίζει το header ενός κομματιού του llms-full.txt από το περιεχόμενο.

    Το header είναι blockquote («This is part N of M … Next part: …»)
    και ακολουθείται από κενές γραμμές ή ``---``.
    """
    lines = text.lstrip('﻿').splitlines()
    if not lines or not _LLMS_HEADER_START_RE.match(lines[0]):
        return '', text

    i = 0
    while i < len(lines) and lines[i].startswith('>'):
        i += 1
    header = '\n'.join(lines[:i])
    while i < len(lines) and lines[i].strip() in ('', '---'):
        i += 1
    return header, '\n'.join(lines[i:])


def fetch_llms_full(guides_base_url):
    """
    Κατεβάζει όλο το ``llms-full.txt`` των οδηγών, ακολουθώντας τα κομμάτια.

    Επιστρέφει το ενιαίο markdown ή ``None`` αν αποτύχει κάποιο κομμάτι.
    Ακολουθούνται μόνο κομμάτια στον ίδιο host με τους οδηγούς.
    """
    base_host = urlparse(guides_base_url).netloc
    url = guides_base_url.rstrip('/') + '/llms-full.txt'
    seen = set()
    parts = []

    while url and url not in seen and len(parts) < LLMS_FULL_MAX_PARTS:
        seen.add(url)
        resp = _http_get(url)
        if resp is None:
            return None

        resp.encoding = 'utf-8'
        header, body = _split_llms_header(resp.text)
        parts.append(_LLMS_FOOTER_RE.sub('', body.rstrip()))

        match = _LLMS_NEXT_PART_RE.search(header)
        next_url = urljoin(url, match.group(1)) if match else None
        if next_url and urlparse(next_url).netloc != base_host:
            log.error('GitBook llms-full.txt next part on another host: %s', next_url)
            return None
        url = next_url

    if url:
        # Σταμάτησε πριν το τέλος (όριο κομματιών ή κύκλος): όχι κομμένος οδηγός
        log.error('GitBook llms-full.txt has more than %s parts or loops (%s)', LLMS_FULL_MAX_PARTS, url)
        return None

    return '\n\n'.join(parts)


def _api_get_json(url, token, params=None):
    """GET στο GitBook API με το token· επιστρέφει dict ή ``None`` σε αποτυχία."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    }
    resp = _http_get(url, headers=headers, params=params)
    if resp is None:
        return None

    try:
        payload = resp.json()
    except ValueError:
        log.error('GitBook API response could not be decoded (%s)', url)
        return None

    return payload if isinstance(payload, dict) else None


def fetch_page_markdown(space_id, token, page_id):
    """
    Επιστρέφει το markdown μίας σελίδας από το GitBook API ή ``None``.
    """
    api_url = GITBOOK_PAGE_CONTENT_ENDPOINT.format(
        space_id=quote(space_id, safe=''),
        page_id=quote(page_id, safe=''),
    )
    payload = _api_get_json(api_url, token, params={'format': 'markdown'})
    if payload is None:
        return None
    page_markdown = payload.get('markdown')
    if not isinstance(page_markdown, str):
        log.error('GitBook page markdown response did not include markdown (%s)', page_id)
        return None

    return _FRONT_MATTER_RE.sub('', page_markdown, count=1)


def _slim_pages(pages):
    """Κρατά μόνο τα πεδία που χρειαζόμαστε από το δέντρο σελίδων (μικρότερη cache)."""
    slim = []
    for page in pages or []:
        item = {key: page.get(key) for key in PAGE_FIELDS}
        item['pages'] = _slim_pages(page.get('pages'))
        slim.append(item)
    return slim


def fetch_space(space_id, token):
    """
    Επιστρέφει ``{'title': ..., 'pages': [...]}`` για το space ή ``None``.

    Ο τίτλος του space είναι αυτός που έβαζε και το PDF export του GitBook.
    """
    quoted = quote(space_id, safe='')
    content = _api_get_json(GITBOOK_SPACE_PAGES_ENDPOINT.format(space_id=quoted), token)
    if content is None:
        return None
    info = _api_get_json(GITBOOK_SPACE_ENDPOINT.format(space_id=quoted), token)
    if info is None:
        return None
    return {
        'title': (info.get('title') or '').strip(),
        'pages': _slim_pages(content.get('pages')),
    }


def _find_page(pages, page_id):
    for page in pages or []:
        if page.get('id') == page_id:
            return page
        found = _find_page(page.get('pages'), page_id)
        if found:
            return found
    return None


def _flatten_visible(page):
    """Η σελίδα και όλες οι ορατές υποσελίδες της (όπως το flattenPage του GitBook)."""
    result = [page]
    for child in page.get('pages') or []:
        if child.get('type') == 'document' and not child.get('hidden'):
            result.extend(_flatten_visible(child))
    return result


def select_pages(pages, page_id=None):
    """
    Οι σελίδες του εγγράφου, με τη σειρά του πίνακα περιεχομένων.

    Χωρίς ``page_id``: όλες οι ορατές σελίδες. Με ``page_id``: η σελίδα και
    οι ορατές υποσελίδες της (όπως το ``page`` + ``only`` του GitBook).
    Επιστρέφει ``None`` αν η σελίδα δεν υπάρχει.
    """
    if page_id:
        page = _find_page(pages, page_id)
        return _flatten_visible(page) if page else None

    selected = []
    for page in pages or []:
        if page.get('type') in ('document', 'group') and not page.get('hidden'):
            selected.extend(_flatten_visible(page))
    return selected


def split_sections(text):
    """Χωρίζει το llms-full.txt σε σελίδες ``(τίτλος, markdown)`` στις επικεφαλίδες H1."""
    sections = []
    title = None
    lines = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _H1_RE.match(line)
        if heading:
            if title is not None:
                sections.append((title, '\n'.join(lines).strip()))
            title = heading.group(1)
            lines = []
        lines.append(line)
    if title is not None:
        sections.append((title, '\n'.join(lines).strip()))
    return sections


def _plain_text(text):
    """Κείμενο χωρίς escapes markdown/HTML και με ενιαία κενά, για συγκρίσεις llms ↔ API."""
    return re.sub(r'\s+', ' ', unescape(_MD_ESCAPE_RE.sub(r'\1', text or ''))).strip()


def _llms_pages(pages, noindex_parent=False):
    """Οι σελίδες που περιέχει το llms-full.txt: όλες εκτός από τις noIndex, με τη σειρά."""
    result = []
    for page in pages or []:
        noindex = noindex_parent or bool(page.get('noIndex'))
        if page.get('type') == 'document' and not noindex:
            result.append(page)
        result.extend(_llms_pages(page.get('pages'), noindex))
    return result


def fetch_llms_sections(guides_base_url, pages):
    """
    Κατεβάζει το llms-full.txt και αντιστοιχίζει κάθε σελίδα του στο id της.

    Επιστρέφει ``{page_id: markdown}`` όταν οι τίτλοι ταιριάζουν ένας προς
    έναν με τις σελίδες του space, αλλιώς ``None`` (και όταν αποτύχει η λήψη).
    """
    text = fetch_llms_full(guides_base_url)
    if text is None:
        return None

    sections = split_sections(text)
    expected = _llms_pages(pages)
    aligned = len(sections) == len(expected) and all(
        _plain_text(title) == _plain_text(page.get('title'))
        for (title, _), page in zip(sections, expected)
    )
    if not aligned:
        log.error(
            'GitBook llms-full.txt does not match the space pages (%s sections, %s pages)',
            len(sections), len(expected),
        )
        return None

    return {page['id']: section for (_, section), page in zip(sections, expected)}


def _replace_liquid_tag(match):
    """Μετατρέπει ένα block του GitBook (``{% … %}``) σε απλό HTML/markdown."""
    name = match.group(1)
    args = dict(_LIQUID_ARG_RE.findall(match.group(2)))

    if name == 'hint':
        style = re.sub(r'[^a-z-]', '', args.get('style', 'info').lower()) or 'info'
        return f'\n\n<div class="hint hint-{style}" markdown="1">\n\n'
    if name == 'endhint':
        return '\n\n</div>\n\n'
    if name == 'tab':
        return f'\n\n<p class="tab-title"><strong>{escape(args.get("title", ""))}</strong></p>\n\n'
    if name == 'embed':
        url = args.get('url', '').strip().strip('<>')
        if not url:
            return ''
        return f'\n\n<p class="embed"><a href="{escape(url)}">{escape(url)}</a></p>\n\n'
    # tabs, stepper/step, columns/column, code, content-ref κ.λπ.:
    # κρατάμε μόνο το περιεχόμενο
    return ''


def _fix_autolink(match):
    """
    Καθαρίζει ένα autolink ``<https://…>`` του llms-full.txt.

    Μέσα σε autolinks το Python-Markdown δεν αφαιρεί τα escapes (``CC\\_BY``),
    και το GitBook μερικές φορές βάζει μέσα και το ``"\\`` της αλλαγής γραμμής.
    """
    inner = match.group(1)
    suffix = ''
    if inner.endswith('\\\\'):
        inner, suffix = inner[:-2], '\\'
    if inner.endswith('"'):
        inner, suffix = inner[:-1], '"' + suffix
    inner = re.sub(r'\\(.)', r'\1', inner)
    return f'<{inner}>{suffix}'


def _unescape_outside_code(line):
    """
    Χειρίζεται escapes του GitBook (``\\&``, ``\\<``, ``\\:``, ``\\ <br>``,
    autolinks) έξω από inline code.
    """
    def fix(segment):
        segment = _AUTOLINK_RE.sub(_fix_autolink, segment)
        segment = _BACKSLASH_BEFORE_BR_RE.sub('<br />', segment)
        return _GITBOOK_ESCAPE_RE.sub(lambda m: _GITBOOK_ESCAPES[m.group(1)], segment)

    out = []
    last = 0
    for match in _INLINE_CODE_RE.finditer(line):
        out.append(fix(line[last:match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(fix(line[last:]))
    return ''.join(out)


def _map_outside_fences(text, transform):
    """Εφαρμόζει ``transform`` σε κάθε γραμμή, εκτός από όσες είναι μέσα σε code fences."""
    out = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            line = transform(line)
        out.append(line)
    return '\n'.join(out)


def _preprocess_line(line):
    line = _LIQUID_TAG_RE.sub(_replace_liquid_tag, line)
    line = _unescape_outside_code(line)
    # Το GitBook βάζει «\» στο τέλος της γραμμής για αλλαγή γραμμής
    if line.endswith('\\') and not line.endswith('\\\\'):
        line = line[:-1] + '<br />'
    # Ανοιχτά <details> ώστε να τυπώνεται το περιεχόμενο, με markdown μέσα
    return _DETAILS_OPEN_RE.sub('<details open markdown="1">', line)


def _preprocess(text):
    """Προσαρμόζει το markdown του GitBook για το Python-Markdown (όχι μέσα σε code fences)."""
    return _map_outside_fences(text, _preprocess_line)


def _cards_table_to_list(match):
    """
    Μετατρέπει έναν πίνακα «cards» του GitBook σε λίστα.

    Οι στήλες με ``data-hidden`` (π.χ. εικόνα εξωφύλλου) παραλείπονται.
    Η στήλη ``data-card-target`` δίνει το link της κάρτας.
    """
    table = match.group(1)
    headers = _TH_RE.findall(table)
    hidden = {i for i, attrs in enumerate(headers) if 'data-hidden' in attrs}
    targets = [i for i, attrs in enumerate(headers) if 'data-card-target' in attrs]
    tbody = table.split('</thead>', 1)[-1]
    items = []
    for row in _TR_RE.findall(tbody):
        row_cells = _TD_RE.findall(row)
        cells = [
            cell.strip() for i, cell in enumerate(row_cells)
            if i not in hidden and cell.strip()
        ]
        target = None
        for i in targets:
            href = _HREF_RE.search(row_cells[i]) if i < len(row_cells) else None
            if href:
                target = href.group(1)
                break
        content = ' '.join(cells)
        if target and content and '<a ' not in content:
            content = f'<a href="{target}">{content}</a>'
        if content:
            items.append('<li>' + content + '</li>')
    if not items:
        return ''
    return '<ul class="cards">' + ''.join(items) + '</ul>'


def _absolutize_urls(html, base_url):
    """Κάνει απόλυτα τα σχετικά links/εικόνες, ως προς τη σελίδα του GitBook."""
    def replace(match):
        prefix, attr, value = match.groups()
        raw = unescape(value)
        # Τα email (<a@b.gr>) βγαίνουν ως mailto: κωδικοποιημένο σε HTML entities
        if not raw or raw.startswith('#') or urlparse(raw).scheme:
            return match.group(0)
        return f'{prefix}{attr}="{escape(urljoin(base_url, raw), quote=True)}"'
    return _TAG_URL_ATTR_RE.sub(replace, html)


def render_gitbook_markdown(text, base_url=None):
    """
    Μετατρέπει markdown του GitBook σε καθαρό HTML για εκτύπωση.

    ``base_url`` είναι η δημοσιευμένη διεύθυνση της σελίδας (ή των οδηγών)
    για να γίνουν απόλυτα τα σχετικά links. Το ``toc`` δίνει ids στις
    επικεφαλίδες (και ελληνικά).
    """
    md = markdown.Markdown(
        extensions=['extra', 'sane_lists', 'toc'],
        extension_configs={'toc': {'slugify': slugify_unicode}},
    )
    html = md.convert(_preprocess(text))
    html = _CARDS_TABLE_RE.sub(_cards_table_to_list, html)
    html = bleach.clean(
        html, tags=PRINT_TAGS, attributes=PRINT_ATTRIBUTES, strip=False,
    )
    # Μετά το bleach, ώστε όλα τα attributes να είναι σε εισαγωγικά
    if base_url:
        html = _absolutize_urls(html, base_url)
    return html


def _absolutize_markdown_links(text, base_url):
    """
    Κάνει απόλυτα τα σχετικά links ενός markdown του API ως προς τη σελίδα του.

    Το API γράφει links σχετικά με τη σελίδα (π.χ. ``leksilogia``), ενώ το
    llms-full.txt σχετικά με τη ρίζα (``/guides/...``). Αφού οι σελίδες
    ενώνονται σε ένα έγγραφο, τα σχετικά links του API λύνονται εδώ.
    """
    def resolve(value):
        if not value or value.startswith(('#', '/')) or urlparse(value).scheme:
            return value
        return urljoin(base_url, value)

    def resolve_line(line):
        line = _MD_LINK_RE.sub(lambda m: m.group(1) + resolve(m.group(2)), line)
        return _URL_ATTR_RE.sub(lambda m: f'{m.group(1)}="{resolve(m.group(2))}"', line)

    return _map_outside_fences(text, resolve_line)


def _style_description(section, description):
    """
    Βάζει την περιγραφή της σελίδας κάτω από τον τίτλο, με ξεχωριστό στυλ.

    Το llms-full.txt την έχει ως απλή παράγραφο μετά το H1· το API όχι.
    """
    description = (description or '').strip()
    head, _, body = section.partition('\n')
    if not description or not _H1_RE.match(head):
        return section

    body = body.lstrip('\n')
    first, _, rest = body.partition('\n')
    if _plain_text(first) == _plain_text(description):
        body = rest.lstrip('\n')
    return f'{head}\n\n<p class="page-description">{escape(description)}</p>\n\n{body}'


def url_hash(url):
    """Σύντομο hash ενός URL για κλειδιά cache (αλλάζει μαζί με το URL)."""
    return hashlib.md5(url.encode('utf-8')).hexdigest()[:12]


def build_document(space_id, token, guides_base_url, page_id=None):
    """
    Έγγραφο εκτύπωσης για όλους τους οδηγούς ή για μία ενότητα.

    Επιστρέφει ``{'title', 'html'}`` ή ``None`` σε αποτυχία.
    Η δομή του space και το llms-full.txt κρατιούνται στη Redis.
    """
    guides_root = guides_base_url.rstrip('/')
    space = get_space(space_id, token)
    if space is None:
        return None

    selected = select_pages(space['pages'], page_id)
    if not selected:
        log.error('GitBook page not found in space %s: %s', space_id, page_id)
        return None

    by_id = get_cached(
        f'gitbook_llms:{url_hash(guides_root)}',
        lambda: fetch_llms_sections(guides_root, space['pages']),
    )
    if by_id is None:
        if not page_id:
            # Ο πλήρης οδηγός θα ήθελε ~300 κλήσεις στο API μέσα στο request·
            # καλύτερα αποτυχία (ανακατεύθυνση στους οδηγούς online)
            log.error('GitBook full guide not built: llms-full.txt unavailable or not aligned')
            return None
        by_id = {}

    missing = [
        page for page in selected
        if page.get('type') == 'document' and page['id'] not in by_id
    ]

    def fetch_missing(page):
        text = fetch_page_markdown(space_id, token, page['id'])
        if text is None:
            return None
        return _absolutize_markdown_links(text, f"{guides_root}/{page.get('path') or ''}")

    with ThreadPoolExecutor(max_workers=MISSING_PAGE_WORKERS) as executor:
        fetched = dict(zip([page['id'] for page in missing], executor.map(fetch_missing, missing)))
    if None in fetched.values():
        return None

    sections = {**by_id, **fetched}
    parts = []
    for page in selected:
        if page.get('type') == 'document':
            parts.append(_style_description(sections[page['id']], page.get('description')))
        else:
            parts.append(f"# {page.get('title') or ''}")

    return {
        'title': space['title'],
        'html': render_gitbook_markdown('\n\n'.join(parts), guides_root + '/'),
    }


def get_space(space_id, token):
    """Η δομή και ο τίτλος του space, από τη Redis ή το GitBook API."""
    return get_cached(f'gitbook_space:{space_id}', lambda: fetch_space(space_id, token))


def get_document(space_id, token, guides_base_url, page_id=None):
    """
    Το έγγραφο εκτύπωσης από τη Redis ή ``build_document``.

    Το κλειδί περιέχει space, οδηγούς και σελίδα, ώστε αλλαγή του
    ``guides_base_url`` να μη σερβίρει παλιό έγγραφο.
    """
    key = f'gitbook_print:{space_id}:{url_hash(guides_base_url)}:{page_id or "full"}'
    return get_cached(key, lambda: build_document(space_id, token, guides_base_url, page_id))
