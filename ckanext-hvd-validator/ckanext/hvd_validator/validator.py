import ipaddress
import logging
import socket
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pyshacl
import rdflib
import requests
from ckan.plugins import toolkit

log = logging.getLogger(__name__)

_HVD_SHAPES_TTL = (
    Path(__file__).parent / "shacl" / "dcat-ap-hvd.shapes.ttl"
).read_text(encoding="utf-8")

_DCATAP_NS = rdflib.Namespace("http://data.europa.eu/r5r/")
_DCAT_NS = rdflib.Namespace("http://www.w3.org/ns/dcat#")
_DCT_NS = rdflib.Namespace("http://purl.org/dc/terms/")
_SH_NS = rdflib.Namespace("http://www.w3.org/ns/shacl#")
_FOAF_NS = rdflib.Namespace("http://xmlns.com/foaf/0.1/")

_OPEN_LICENSE_MARKERS = (
    "creativecommons.org/licenses/by",
    "publications.europa.eu/resource/authority/licence/cc_by",
    "publications.europa.eu/resource/authority/licence/cc0",
    "creativecommons.org/publicdomain/zero",
    "opendefinition.org/licenses/cc-by",
    "opendefinition.org/licenses/odc-by",
    "opendatacommons.org/licenses/by",
)

_hvd_vocab_cache: dict = {}
_hvd_vocab_lock = threading.Lock()

_URL_FETCH_TIMEOUT = 30
_VOCAB_FETCH_TIMEOUT = 5
_MAX_REDIRECTS = 3
_MAX_FETCH_BYTES = 2 * 1024 * 1024
_FETCH_CHUNK_BYTES = 64 * 1024
_MAX_VOCAB_REFS = 20

_HVD_PATH_LABELS = {
    "applicableLegislation": "the applicable EU legislation citation",
    "hvdCategory": "the HVD category classification",
    "servesDataset": "the link back to the dataset this API serves",
    "endpointURL": "the API's endpoint URL",
    "endpointDescription": "the API's endpoint documentation",
    "contactPoint": "the dataset's contact point",
    "page": "the documentation/reference page",
    "rights": "the rights statement",
    "license": "the license",
    "conformsTo": "the standard/specification it conforms to",
    "distribution": "at least one distribution (downloadable file/API)",
    "inSeries": "the dataset series it belongs to",
    "hasEmail": "the contact point's email address",
    "hasURL": "the contact point's web address",
    "inScheme": "the vocabulary/scheme reference",
    "accessService": "the linked API (access service)",
    "accessURL": "the API's access URL",
}

_LICENSE_VOCAB_MARKERS = ("skos:exactMatch", "owl:sameAs", "skos:broadMatch")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class UnsafeFetchUrl(ValueError):
    pass


class FetchResponseTooLarge(ValueError):
    pass


def _is_blocked_ip(ip_address: str) -> bool:
    ip = ipaddress.ip_address(ip_address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeFetchUrl("Only HTTP(S) URLs can be fetched.")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeFetchUrl("URL hostname is missing.")

    hostname = hostname.strip().lower().rstrip(".")
    if hostname == "localhost" or "." not in hostname:
        raise UnsafeFetchUrl("Local hostnames cannot be fetched.")

    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeFetchUrl("URL hostname could not be resolved.") from exc

    resolved_ips = {info[4][0] for info in addr_infos}
    if not resolved_ips:
        raise UnsafeFetchUrl("URL hostname did not resolve to an IP address.")

    for resolved_ip in resolved_ips:
        if _is_blocked_ip(resolved_ip):
            raise UnsafeFetchUrl("URL resolves to a blocked network address.")


def _safe_get(url: str, *, timeout, headers, stream: bool = False):
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        _validate_fetch_url(current_url)
        response = requests.get(
            current_url,
            timeout=timeout,
            headers=headers,
            allow_redirects=False,
            stream=stream,
        )
        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                raise UnsafeFetchUrl("Redirect response is missing a Location header.")
            current_url = urljoin(current_url, location)
            continue
        return response
    raise UnsafeFetchUrl("Too many redirects while fetching URL.")


def _read_limited_response_text(response, max_bytes: int = _MAX_FETCH_BYTES) -> str:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise FetchResponseTooLarge("Fetched response exceeds the size limit.")
        except ValueError as exc:
            if isinstance(exc, FetchResponseTooLarge):
                raise

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=_FETCH_CHUNK_BYTES, decode_unicode=False):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise FetchResponseTooLarge("Fetched response exceeds the size limit.")
        chunks.append(chunk)

    data = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    return data.decode(encoding, errors="replace")


def _safe_get_text(url: str, *, timeout, headers):
    response = _safe_get(url, timeout=timeout, headers=headers, stream=True)
    response.raise_for_status()
    return (
        _read_limited_response_text(response),
        response.headers,
    )


def _vocab_refs(graph: rdflib.Graph) -> list[rdflib.URIRef]:
    seen = set()
    refs = []
    for predicate in (
        _DCATAP_NS.hvdCategory,
        _DCAT_NS.accessService,
        _DCT_NS.license,
    ):
        for ref in graph.objects(None, predicate):
            if not isinstance(ref, rdflib.URIRef):
                continue
            ref_s = str(ref)
            if ref_s in seen:
                continue
            seen.add(ref_s)
            refs.append(ref)
    return refs


def _get_vocab_graph(url: str):
    with _hvd_vocab_lock:
        if url in _hvd_vocab_cache:
            return _hvd_vocab_cache[url]
    g = None
    try:
        text, _headers = _safe_get_text(
            url,
            timeout=_VOCAB_FETCH_TIMEOUT,
            headers={
                "Accept": "application/rdf+xml",
                "User-Agent": "CKAN-HVD-Validator/1.0",
            },
        )
        g = rdflib.Graph()
        g.parse(data=text, format="xml")
    except UnsafeFetchUrl as exc:
        log.warning("Blocked unsafe HVD vocabulary URL %s: %s", url, exc)
        g = None
    except FetchResponseTooLarge as exc:
        log.warning("Skipped oversized HVD vocabulary URL %s: %s", url, exc)
        g = None
    except Exception:
        g = None
    with _hvd_vocab_lock:
        _hvd_vocab_cache[url] = g
    return g


def _augment_with_vocab(graph: rdflib.Graph) -> None:
    refs = _vocab_refs(graph)
    if len(refs) > _MAX_VOCAB_REFS:
        log.warning(
            "HVD vocabulary augmentation limited to %s of %s referenced URIs",
            _MAX_VOCAB_REFS,
            len(refs),
        )
        refs = refs[:_MAX_VOCAB_REFS]

    for ref in refs:
        vocab_graph = _get_vocab_graph(str(ref))
        if vocab_graph is not None:
            graph += vocab_graph


def _license_status(graph: rdflib.Graph) -> str:
    licenses = list(graph.objects(None, _DCT_NS.license))
    if not licenses:
        return "missing"
    for lic in licenses:
        if any(marker in str(lic).lower() for marker in _OPEN_LICENSE_MARKERS):
            return "open"
    return "non_open"


def _generic_property_message(path_s: str, comp, path_labels: dict) -> str | None:
    local = path_s.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if path_s else ""
    label = path_labels.get(local)
    if not label:
        return None
    label = toolkit._(label)
    if comp == _SH_NS.MinCountConstraintComponent:
        return toolkit._("Missing {label}.").format(label=label)
    if comp == _SH_NS.NodeKindConstraintComponent:
        return toolkit._(
            "{label} isn't a properly linked resource "
            "(a plain value instead of a URI)."
        ).format(label=label)
    if comp == _SH_NS.ClassConstraintComponent:
        return toolkit._(
            "{label} doesn't reference the expected type of resource."
        ).format(label=label)
    if comp == _SH_NS.DatatypeConstraintComponent:
        return toolkit._("{label} has the wrong data type.").format(label=label)
    return toolkit._("Issue with {label}.").format(label=label)


def _friendly_shacl_message(path_s: str, comp, raw_msg: str) -> str:
    if "applicableLegislation" in path_s:
        if comp == _SH_NS.ClassConstraintComponent:
            return (
                toolkit._(
                    "The cited legislation isn't linked to a recognized EU legal "
                    "resource (ELI) — likely plain text instead of the official reference."
                )
            )
        return toolkit._(
            "The applicable HVD legislation isn't cited as a properly linked legal resource."
        )

    if "accessService" in path_s or "accessService" in raw_msg:
        if comp == _SH_NS.MinCountConstraintComponent:
            return toolkit._(
                "No API (data access service) is linked to this dataset, as HVD rules require."
            )
        if comp == _SH_NS.ClassConstraintComponent:
            return toolkit._(
                "An API is linked, but it isn't described as a proper dcat:DataService."
            )
        if comp == _SH_NS.NodeKindConstraintComponent:
            return toolkit._(
                "An API is linked, but only inline — it has no stable web address of its own."
            )

    if any(marker in raw_msg for marker in _LICENSE_VOCAB_MARKERS):
        return toolkit._(
            "The dataset's license couldn't be matched to a known open-license entry in the EU's vocabulary."
        )

    return (
        _generic_property_message(path_s, comp, _HVD_PATH_LABELS)
        or raw_msg
        or toolkit._("Unrecognized SHACL validation issue.")
    )


def _dedupe_shacl_details(entries: list) -> list:
    deduped, index = [], {}
    for e in entries:
        key = (e["severity"], e["message"])
        if key in index:
            index[key]["count"] += 1
        else:
            entry = dict(e, count=1)
            index[key] = entry
            deduped.append(entry)
    return deduped


def _classify_shacl_results(results_graph: rdflib.Graph):
    violations, warnings = [], []
    legal_citation_issue = False
    no_api_access = False
    for r in results_graph.subjects(rdflib.RDF.type, _SH_NS.ValidationResult):
        sev = results_graph.value(r, _SH_NS.resultSeverity)
        msg = results_graph.value(r, _SH_NS.resultMessage)
        path = results_graph.value(r, _SH_NS.resultPath)
        shape = results_graph.value(r, _SH_NS.sourceShape)
        comp = results_graph.value(r, _SH_NS.sourceConstraintComponent)
        path_s = str(path) if path is not None else ""
        shape_s = str(shape) if shape is not None else ""
        raw_msg = str(msg) if msg else ""
        entry = {
            "severity": "violation" if sev == _SH_NS.Violation else "warning",
            "path": path_s or None,
            "message": _friendly_shacl_message(path_s, comp, raw_msg),
            "raw_message": raw_msg,
        }
        if sev == _SH_NS.Violation:
            violations.append(entry)
            if "applicableLegislation" in path_s and (
                "DatasetShape" in shape_s or "DistributionShape" in shape_s
            ):
                legal_citation_issue = True
            if (
                shape_s.endswith("DatasetShape/API")
                and comp == _SH_NS.MinCountConstraintComponent
            ):
                no_api_access = True
        else:
            warnings.append(entry)
    return violations, warnings, legal_citation_issue, no_api_access


def _guess_format(filename_or_url: str, content_type: str) -> str:
    lower = filename_or_url.lower()
    if lower.endswith(".ttl"):
        return "turtle"
    if lower.endswith(".jsonld") or lower.endswith(".json-ld"):
        return "json-ld"
    if lower.endswith(".n3"):
        return "n3"
    if lower.endswith(".nt"):
        return "nt"
    if "json" in content_type:
        return "json-ld"
    if "turtle" in content_type:
        return "turtle"
    return "xml"


def _parse_graph(data, source: str, content_type: str = "") -> rdflib.Graph:
    graph = rdflib.Graph()
    fmt = _guess_format(source, content_type)
    graph.parse(data=data, format=fmt)
    return graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_hvd_graph(graph: rdflib.Graph) -> dict:
    _augment_with_vocab(graph)

    conforms, results_graph, _ = pyshacl.validate(
        graph,
        shacl_graph=_HVD_SHAPES_TTL,
        shacl_graph_format="turtle",
        advanced=True,
        inference="rdfs",
        debug=False,
    )
    violations, warnings, legal_citation_issue, no_api_access = (
        _classify_shacl_results(results_graph)
    )

    title = None
    for t in graph.objects(None, _DCT_NS.title):
        title = str(t)
        break

    publisher_name = None
    for publisher in graph.objects(None, _DCT_NS.publisher):
        name_lit = graph.value(publisher, _FOAF_NS.name)
        if name_lit:
            publisher_name = str(name_lit)
            break

    return {
        "title": title,
        "publisher_name": publisher_name or "",
        "conforms": conforms,
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "legal_citation_issue": legal_citation_issue,
        "no_api_access": no_api_access,
        "license_status": _license_status(graph),
        "details": _dedupe_shacl_details(violations + warnings),
    }


def validate_from_url(url: str) -> dict:
    try:
        text, headers = _safe_get_text(
            url,
            timeout=_URL_FETCH_TIMEOUT,
            headers={
                "Accept": "application/rdf+xml",
                "User-Agent": "CKAN-HVD-Validator/1.0",
            },
        )
    except UnsafeFetchUrl as exc:
        raise ValueError(
            toolkit._("This URL cannot be fetched by the validator.")
        ) from exc
    except FetchResponseTooLarge as exc:
        raise ValueError(
            toolkit._("The fetched RDF document exceeds the size limit.")
        ) from exc
    graph = _parse_graph(text, url, headers.get("Content-Type", ""))
    result = validate_hvd_graph(graph)
    result["source"] = url
    return result


def validate_from_name(name: str, context: dict) -> dict:
    try:
        dcat_dataset_show = toolkit.get_action("dcat_dataset_show")
    except KeyError as exc:
        raise ValueError(toolkit._("DCAT RDF export is not available.")) from exc

    try:
        rdf_data = dcat_dataset_show(
            context,
            {
                "id": name,
                "format": "rdf",
            },
        )
    except toolkit.NotAuthorized as exc:
        raise ValueError(
            toolkit._("You are not authorized to view this dataset.")
        ) from exc
    except toolkit.ObjectNotFound as exc:
        raise ValueError(toolkit._("Dataset not found.")) from exc

    graph = _parse_graph(rdf_data, f"{name}.rdf", "application/rdf+xml")
    result = validate_hvd_graph(graph)
    result["name"] = name
    result["source"] = f"ckan:dataset:{name}"
    return result


def validate_from_file(file_data: bytes, filename: str) -> dict:
    graph = _parse_graph(file_data, filename)
    result = validate_hvd_graph(graph)
    result["source"] = f"upload:{filename}"
    return result
