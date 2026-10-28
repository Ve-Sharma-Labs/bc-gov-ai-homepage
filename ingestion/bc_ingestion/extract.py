"""Section-preserving extraction with conservative publication quality flags."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment

from .fetch import Response
from .metadata import EXTRACTION_METHOD, MAX_CHUNK_CHARS, extraction_digest, iso_datetime, legal_date, validate_metadata
from .policy import AcquisitionError, canonicalize, validate_url


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class Section:
    heading: str
    text: str
    locator: str
    contains_exceptions: bool = False
    blocks: list[dict] = field(default_factory=list)


@dataclass
class Document:
    url: str
    title: str
    checked_at: str
    publisher_updated_at: str | None
    content_hash: str
    response_hash: str
    quality: str
    flags: list[str]
    sections: list[Section]
    links: list[dict]
    aliases: list[str] = field(default_factory=list)
    extraction_method: str = EXTRACTION_METHOD
    metadata: dict = field(default_factory=dict)
    extraction_hash: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


MAINTENANCE = re.compile(
    r"temporarily unavailable|under maintenance|down for maintenance|"
    r"scheduled maintenance|service unavailable|website maintenance|"
    r"access denied|verify (?:that )?you are human|checking your browser", re.I
)
EXCEPTION = re.compile(r"\b(?:except(?:ions)?|exclusions?|excluding|excluded|ineligible|not (?:be )?eligible|cannot|must not|not available|unavailable|unless|however)\b", re.I)
PARTIAL = re.compile(r"^(?:loading[.\u2026 ]*|enable javascript.*|please enable javascript.*)$", re.I)
FURNITURE = re.compile(r"privacy|copyright|accessibility|contact us|disclaimer", re.I)

STRUCTURED_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "address"]


def _reference_text(root, target, table) -> str:
    """Keep a referenced definition's whole heading section, including qualifications."""
    if target is table or target.find_parent("table") is table:
        if target.name == "tfoot" or target.find_parent("tfoot") is not None:
            block = target if target.name in ("tr", "tfoot") else target.find_parent("tr")
            return clean_text(block.get_text(" ", strip=True))
        raise AcquisitionError("Table references another table row/group")
    block = target if target.name in STRUCTURED_TAGS else target.find_parent(STRUCTURED_TAGS)
    if block is None:
        block = target if target.get_text(strip=True) else target.find_next(STRUCTURED_TAGS)
    if block is None or (block is not root and root not in block.parents):
        raise AcquisitionError("Referenced definition is outside the extracted main region")
    heading = block if re.fullmatch(r"h[1-6]", block.name) else block.find_previous(re.compile(r"^h[1-6]$"))
    if heading is not None and root in heading.parents:
        level = int(heading.name[1])
        collected, contains_table = [clean_text(heading.get_text(" ", strip=True))], False
        for node in heading.find_all_next(STRUCTURED_TAGS):
            if root not in node.parents:
                break
            if re.fullmatch(r"h[1-6]", node.name) and int(node.name[1]) <= level:
                break
            if node.name == "table":
                contains_table = True
                break
            if node.find_parent(["li", "p", "table"]) is None:
                collected.append(clean_text(node.get_text(" ", strip=True)))
        if not contains_table and any(collected):
            return "\n".join(text for text in collected if text)
        if contains_table and re.fullmatch(r"h[1-6]", block.name):
            raise AcquisitionError("Referenced heading contains the table itself; row-group review is required")
    # A footnote after its own table must not expand the entire table recursively.
    collected = [clean_text(block.get_text(" ", strip=True))]
    for node in block.find_all_next(STRUCTURED_TAGS):
        if root not in node.parents or node.name == "table" or re.fullmatch(r"h[1-6]", node.name):
            break
        if block in node.parents or node.find_parent(["li", "p", "table"]) is not None:
            continue
        if node.get("id") or node.find(id=True) or node.find("a", attrs={"name": True}):
            break
        collected.append(clean_text(node.get_text(" ", strip=True)))
    text = "\n".join(part for part in collected if part)
    if not text:
        raise AcquisitionError("Empty referenced qualification")
    return text


def _table_block(node, root, page_url: str, flags: list[str]) -> dict:
    headers, rows, row_references, footers, references = [], [], [], [], {}
    global_refs = set((node.get("aria-describedby") or "").split())

    def local_refs(element):
        result = set()
        for link in element.find_all("a", href=True):
            try:
                parts = urlsplit(urljoin(page_url, link["href"]))
                if parts.fragment and canonicalize(parts.geturl()) == canonicalize(page_url):
                    result.add(unquote(parts.fragment))
            except AcquisitionError:
                continue
        return result

    caption = node.find("caption", recursive=False)
    caption_text = clean_text(caption.get_text(" ", strip=True)) if caption else ""
    if caption:
        global_refs.update(local_refs(caption))
    complex_table = bool(node.find("table") or node.select("[rowspan]:not([rowspan='1']), [colspan]:not([colspan='1'])"))
    for row in node.find_all("tr"):
        if row.find_parent("table") is not node:
            continue
        cells = row.find_all(["td", "th"], recursive=False)
        text = " | ".join(clean_text(c.get_text(" ", strip=True)) for c in cells)
        if not cells and row.get_text(strip=True):
            text = clean_text(row.get_text(" ", strip=True))
            flags.append("table-structure-review-required")
        if not text:
            continue
        refs = local_refs(row)
        if row.find_parent("tfoot") is not None:
            footers.append(text)
            global_refs.update(refs)
        elif not row.find("td") and (row.find_parent("thead") or not rows):
            headers.append(text)
            global_refs.update(refs)
        else:
            rows.append(text)
            row_references.append(sorted(refs))
    wanted = global_refs | {key for keys in row_references for key in keys}
    for key in sorted(wanted):
        targets = root.find_all(id=key)
        if not targets:
            targets = root.find_all("a", attrs={"name": key})
        if len(targets) != 1:
            flags.append("table-reference-review-required")
            continue
        try:
            references[key] = _reference_text(root, targets[0], node)
        except AcquisitionError:
            flags.append("table-reference-review-required")
    return {
        "kind": "table", "text": "\n".join(([caption_text] if caption_text else []) + headers + rows + footers),
        "headers": headers, "rows": rows, "caption": caption_text, "complex": complex_table,
        "footers": footers, "references": references, "rowReferences": row_references,
        "globalReferences": sorted(global_refs),
    }


def _table_fragment(block: dict, indices: list[int]) -> str:
    references = set(block.get("globalReferences", []))
    for index in indices:
        if block.get("rowReferences"):
            references.update(block["rowReferences"][index])
    definitions = {}
    for key in sorted(references):
        text = block.get("references", {}).get(key)
        if text:
            definitions.setdefault(text, []).append("#" + key)
    text = "\n".join(
        ([block["caption"]] if block.get("caption") else [])
        + block["headers"] + [block["rows"][i] for i in indices] + block.get("footers", [])
    )
    if definitions:
        text += "\n\nReferenced qualifications:\n" + "\n\n".join(
            ", ".join(keys) + "\n" + definition for definition, keys in definitions.items()
        )
    return text


def _section_text(section: Section) -> str:
    if not section.blocks:
        return section.text
    return "\n".join(
        _table_fragment(block, list(range(len(block["rows"]))))
        if block["kind"] == "table" and block.get("references") else block["text"]
        for block in section.blocks
    )


def extract(response: Response, *, url_validator=validate_url, canonical_validator=None,
            metadata: dict | None = None, quality_flags=()) -> Document:
    if response.status != 200:
        raise AcquisitionError(f"HTTP {response.status} is not extractable guidance")
    if response.headers.get("content-type", "").split(";")[0].lower() not in (
        "text/html", "application/xhtml+xml",
    ):
        raise AcquisitionError("unsupported-format: only direct public HTML extraction is implemented")
    soup = BeautifulSoup(response.body, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    body_text = clean_text(soup.get_text(" ", strip=True))
    flags = list(quality_flags)
    url = canonicalize(response.url)
    canonical = soup.find("link", rel="canonical")
    aliases = list(response.aliases)
    if canonical and canonical.get("href"):
        try:
            candidate = url_validator(urljoin(url, canonical["href"]))
            if urlsplit(candidate).hostname != urlsplit(url).hostname:
                raise AcquisitionError("Cross-host canonical")
            if candidate != url:
                if canonical_validator is None:
                    raise AcquisitionError("Canonical target needs a separate access/robots check")
                canonical_validator(candidate)
                aliases.append(url)
                url = candidate
        except AcquisitionError:
            flags.append("unapproved-canonical")
    # An actual content region is required; body/footer fallback is quarantined.
    root = soup.select_one("main, [role=main]")
    if root is None:
        root = next(
            (n for n in soup.select("#main-content, #mainContent, #main-content-area")
             if n.name not in ("a", "span") and len(n.get_text(strip=True)) > 100),
            None,
        )
    if root is None:
        root = soup.select_one(".topicMain__container")
    if root is None:
        root = soup.select_one("article.node--view-mode-full, article")
    if root is None:
        root = soup.body or soup
        flags.append("missing-main-region")
    for element in root.select("script, style, nav, footer, header, noscript, form, [aria-hidden=true]"):
        element.decompose()
    for element in root.select(".field--name-field-accordion-item-title, summary, [role=heading]"):
        element.name = "h3"
    texts = [clean_text(t) for t in root.stripped_strings]
    if any(PARTIAL.match(t) for t in texts) or re.search(r"enable javascript", body_text, re.I):
        flags.append("dynamic-or-incomplete")
    root_text = clean_text(root.get_text(" ", strip=True))
    if MAINTENANCE.search(title) or (
        len(root_text) < 2500 and MAINTENANCE.search(root_text)
    ):
        flags.append("maintenance-or-access-page")
    if len(root_text) < 300:
        flags.append("too-little-guidance")
    if FURNITURE.search(root_text) and len(root_text) < 700 and not root.find(["h1", "h2"]):
        flags.append("footer-only")
    if not title or not root.find(["h1", "h2"]):
        flags.append("missing-title-or-headings")
    if urlsplit(url).hostname == "www.icbc.com":
        # The approved discovery found unresolved dynamic modules. No direct HTML
        # response can clear this source-wide hold without a reviewed rendered/feed route.
        flags.append("icbc-rendering-review-required")
    if urlsplit(url).hostname == "www.bchousing.org":
        flags.append("publisher-freshness-review-required")
    if re.search(r"(?:updates? (?:are |have been )?paused|content (?:is )?current (?:as of|to))", body_text, re.I):
        flags.append("publisher-freshness-notice")
    if re.search(r"ignore (?:all |previous |prior )?instructions|system prompt", root_text, re.I):
        flags.append("prompt-like-content")
    sections, paragraphs, blocks = [], [], []
    heading, locator = title, "document"
    heading_stack: dict[int, str] = {}

    def flush():
        if paragraphs:
            text = "\n".join(paragraphs)
            sections.append(Section(heading, text, locator, bool(EXCEPTION.search(text)), list(blocks)))
            paragraphs.clear()
            blocks.clear()

    for node in root.find_all(STRUCTURED_TAGS):
        if node.find_parent(["table", "li"]) is not None:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if re.fullmatch(r"h[1-6]", node.name):
            flush()
            level = int(node.name[1])
            heading_stack = {k: v for k, v in heading_stack.items() if k < level}
            heading_stack[level] = text
            heading = " > ".join(heading_stack.values())
            locator = node.get("id") or f"section-{len(sections) + 1}"
        elif node.name == "table":
            block = _table_block(node, root, response.url, flags)
            paragraphs.append(block["text"])
            blocks.append(block)
            if block["complex"]:
                flags.append("complex-table-review-required")
        else:
            paragraphs.append(text)
            blocks.append({"kind": "text", "text": text})
    flush()
    unstructured = clean_text(" ".join(
        str(text) for text in root.find_all(string=True)
        if not isinstance(text, Comment) and text.find_parent(
            STRUCTURED_TAGS
        ) is None
    ))
    if EXCEPTION.search(unstructured):
        flags.append("unstructured-exclusion-review-required")
        sections.append(Section(
            "Unstructured guidance requiring review", unstructured, "unstructured", True,
            [{"kind": "text", "text": unstructured}],
        ))
    extracted = "\n".join(s.heading + "\n" + s.text for s in sections)
    if len(extracted) < 300 or len(extracted) < len(root_text) * 0.35:
        flags.append("incomplete-structured-extraction")
    links, seen = [], set()
    for link in root.find_all("a", href=True):
        try:
            candidate = canonicalize(urljoin(response.url, link["href"]))
        except AcquisitionError:
            continue
        if candidate not in seen:
            seen.add(candidate)
            links.append({"url": candidate, "label": clean_text(link.get_text(" ", strip=True))})
    updated = None
    for meta in soup.select("meta[property='article:modified_time'], meta[name='dcterms.modified']"):
        candidate = meta.get("content", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+Z?)?", candidate):
            updated = candidate
            break
    if updated is None:
        for time_node in soup.find_all("time", datetime=True):
            if re.search(r"updated|modified", time_node.parent.get_text(" ", strip=True), re.I):
                candidate = time_node["datetime"]
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+Z?)?", candidate):
                    updated = candidate
                    break
    if updated is None:
        label = soup.select_one(".last_Updated_Text")
        if label:
            match = re.search(r"Last updated on (\w+ \d{1,2}, \d{4})", label.get_text(" ", strip=True))
            if match:
                try:
                    updated = datetime.strptime(match[1], "%B %d, %Y").date().isoformat()
                except ValueError:
                    flags.append("invalid-publisher-date")
    if updated is not None:
        try:
            legal_date(updated) if len(updated) == 10 else iso_datetime(updated)
        except AcquisitionError:
            updated = None
            flags.append("invalid-publisher-date")
    provenance = {
        "schemaVersion": 1, "sourceIds": [], "topics": [], "documentType": "guidance",
        "rights": None, "legal": None, **(metadata or {}),
        "canonicalUrl": url, "sourceUrl": canonicalize(response.url),
        "mediaType": response.headers["content-type"].split(";")[0].strip().lower(),
        "language": soup.html.get("lang") if soup.html else None,
    }
    try:
        validate_metadata(provenance)
    except AcquisitionError:
        if provenance["language"]:
            provenance["language"] = None
            flags.append("invalid-language-tag")
        validate_metadata(provenance)
    document = Document(
        url, title, response.checked_at, updated,
        hashlib.sha256(extracted.encode("utf-8")).hexdigest(), response.digest,
        "quarantined" if flags else "review-required", sorted(set(flags)),
        sections, links, aliases, metadata=provenance,
    )
    document.extraction_hash = extraction_digest(document)
    try:
        chunk_document(document)
    except ChunkingError as exc:
        document.flags = sorted(set([*document.flags, exc.reason]))
        document.quality = "quarantined"
    return document


class ChunkingError(AcquisitionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason + ": full extraction retained; no incomplete chunks may be published")


def legacy_chunks(document: Document, target_chars: int = 2400) -> list[dict]:
    """Only for locating old published keys, never for new uploads."""
    chunks, pending, size = [], [], 0
    for section in document.sections:
        # Exceptions stay with the preceding context even if that exceeds target.
        if pending and size + len(section.text) > target_chars and not (
            section.contains_exceptions or EXCEPTION.search(section.heading)
        ):
            chunks.append(_chunk(pending))
            pending, size = [], 0
        pending.append(section)
        size += len(section.text)
    if pending:
        chunks.append(_chunk(pending))
    return chunks


def chunk_document(document: Document, target_chars: int = 2400,
                   max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """Hard cap with repeated exclusions and row/header-preserving table splits."""
    if not 1 <= target_chars <= MAX_CHUNK_CHARS or not 1 <= max_chars <= MAX_CHUNK_CHARS:
        raise AcquisitionError("Chunk limits must be between 1 and 8000 characters")
    groups, pending, size = [], [], 0
    for section in document.sections:
        if pending and size + len(section.text) > target_chars and not (
            section.contains_exceptions or EXCEPTION.search(section.heading)
        ):
            groups.append(pending)
            pending, size = [], 0
        pending.append(section)
        size += len(section.text)
    if pending:
        groups.append(pending)
    result = []
    for group in groups:
        complete = _chunk(group)
        if len(complete["content"]) <= max_chars:
            result.append(complete)
        else:
            result.extend(_split_group(group, max_chars))
    return result


def _split_group(sections: list[Section], limit: int) -> list[dict]:
    context, work = [], []
    for section in sections:
        if not section.blocks and len(section.heading + "\n" + section.text) > limit:
            raise ChunkingError("legacy-structure-review-required")
        blocks = section.blocks or [{"kind": "text", "text": section.text}]
        has_table = any(block["kind"] == "table" for block in blocks)
        for block in blocks:
            heading = section.heading + "\n"
            # Table exclusions are row-local and stay beside their row identifiers.
            # Prose exclusions, captions/footnotes and introductions surround every part.
            if block["kind"] != "table" and (
                has_table or EXCEPTION.search(section.heading) or EXCEPTION.search(block["text"])
            ):
                context.append(heading + block["text"])
            else:
                work.append((section, block))
    prefix = "\n\n".join(dict.fromkeys(context))
    if prefix:
        prefix += "\n\n"
    capacity = limit - len(prefix)
    if capacity < 100:
        raise ChunkingError("oversized-required-context")
    units = []
    for section, block in work:
        heading = section.heading + "\n"
        available = capacity - len(heading)
        if available < 100:
            raise ChunkingError("oversized-section-heading")
        if block["kind"] == "table":
            complete = _table_fragment(block, list(range(len(block["rows"]))))
            if len(complete) <= available:
                units.append(heading + complete)
                continue
            if block.get("complex") or not block.get("headers"):
                raise ChunkingError("oversized-table-structure-review-required")
            indices = []
            for index, row in enumerate(block["rows"]):
                if len("\n".join(block["headers"] + [row] + block.get("footers", []))) > available:
                    raise ChunkingError("oversized-table-row")
                if len(_table_fragment(block, [index])) > available:
                    raise ChunkingError("oversized-table-reference-context")
                if indices and len(_table_fragment(block, indices + [index])) > available:
                    units.append(heading + _table_fragment(block, indices))
                    indices = []
                indices.append(index)
            if indices:
                units.append(heading + _table_fragment(block, indices))
        else:
            text = block["text"]
            while len(text) > available:
                boundary = text.rfind(" ", 0, available + 1)
                if boundary < 1:
                    raise ChunkingError("oversized-unbroken-text")
                units.append(heading + text[:boundary])
                text = text[boundary + 1:]
            if text:
                units.append(heading + text)
    if not units:
        raise ChunkingError("oversized-required-context")
    pieces, pending = [], ""
    for unit in units:
        if pending and len(pending) + 2 + len(unit) > capacity:
            pieces.append(prefix + pending)
            pending = ""
        pending = pending + "\n\n" + unit if pending else unit
    if pending:
        pieces.append(prefix + pending)
    return [{
        "section": sections[0].heading, "locators": [s.locator for s in sections],
        "content": text, "containsExceptions": bool(context) or any(
            s.contains_exceptions or EXCEPTION.search(s.heading) for s in sections
        ), "partIndex": index + 1, "partCount": len(pieces),
    } for index, text in enumerate(pieces)]


def _chunk(sections: list[Section]) -> dict:
    return {
        "section": sections[0].heading,
        "locators": [s.locator for s in sections],
        "content": "\n\n".join(s.heading + "\n" + _section_text(s) for s in sections),
        "containsExceptions": any(bool(s.contains_exceptions or EXCEPTION.search(s.heading)) for s in sections),
    }
