"""Offline, bounded primary-text PDF extraction; no OCR, widgets or transactions."""

from dataclasses import dataclass
from io import BytesIO
import zlib

from pypdf import PdfReader, apply_configuration
from pypdf.generic import ArrayObject, DictionaryObject, StreamObject

from .extract import Document, EXCEPTION, Section, clean_text
from .fetch import Response
from .metadata import PDF_EXTRACTION_METHOD, extraction_digest, validate_metadata
from .policy import AcquisitionError, canonicalize


class PDFExtractionError(AcquisitionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"pdf-quarantine: {reason}")


@dataclass(frozen=True)
class PDFLimits:
    max_bytes: int = 4_000_000
    max_pages: int = 100
    max_text_chars: int = 1_000_000
    max_stream_bytes: int = 4_000_000
    max_decoded_bytes: int = 16_000_000

    def __post_init__(self):
        for name, ceiling in (
            ("max_bytes", 8_000_000), ("max_pages", 100),
            ("max_text_chars", 1_000_000), ("max_stream_bytes", 4_000_000),
            ("max_decoded_bytes", 16_000_000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise PDFExtractionError(f"invalid-limit: {name}")


def _preflight_streams(pages, limits: PDFLimits) -> None:
    """Check content/Form expansion before pypdf's text interpreter decodes it."""
    sizes, active, resource_seen, resource_done = {}, set(), set(), set()
    total = 0

    def stream_size(stream):
        nonlocal total
        if not isinstance(stream, StreamObject):
            raise PDFExtractionError("invalid-content-stream")
        if id(stream) in sizes:
            total += sizes[id(stream)]
            if total > limits.max_decoded_bytes:
                raise PDFExtractionError("total-decoded-byte-limit")
            return
        filters = stream.get("/Filter", [])
        filters = list(filters) if isinstance(filters, ArrayObject) else [filters] if filters else []
        parameters = stream.get("/DecodeParms")
        if parameters:
            raise PDFExtractionError("unsupported-content-decode-parameters")
        data = stream._data
        if filters == ["/FlateDecode"]:
            decoder = zlib.decompressobj()
            data = decoder.decompress(data, limits.max_stream_bytes + 1)
            if len(data) > limits.max_stream_bytes or decoder.unconsumed_tail:
                raise PDFExtractionError("decoded-stream-byte-limit")
            if not decoder.eof or decoder.unused_data:
                raise PDFExtractionError("invalid-compressed-content-stream")
        elif filters:
            raise PDFExtractionError("unsupported-content-stream-filter")
        if len(data) > limits.max_stream_bytes:
            raise PDFExtractionError("decoded-stream-byte-limit")
        sizes[id(stream)] = len(data)
        total += len(data)
        if total > limits.max_decoded_bytes:
            raise PDFExtractionError("total-decoded-byte-limit")

    def resource_streams(reference, depth=0):
        obj = reference.get_object()
        if id(obj) in resource_seen:
            return
        resource_seen.add(id(obj))
        if depth > 32 or len(resource_seen) > 4096:
            raise PDFExtractionError("resource-complexity-limit")
        if isinstance(obj, StreamObject):
            if obj.get("/Subtype") == "/Image":
                return  # Text extraction does not decode images.
            stream_size(obj)
        if isinstance(obj, DictionaryObject):
            for value in obj.values():
                resource_streams(value, depth + 1)
        elif isinstance(obj, ArrayObject):
            for value in obj:
                resource_streams(value, depth + 1)

    def resources(node, depth=0):
        if depth > 16 or id(node) in active:
            raise PDFExtractionError("cyclic-or-deep-form-resources")
        if id(node) in resource_done:
            return
        active.add(id(node))
        resource = node.get("/Resources")
        if resource:
            # Font files and ToUnicode maps can also contain compressed streams.
            resource_streams(resource)
            objects = resource.get_object().get("/XObject")
            if objects:
                for reference in objects.get_object().values():
                    obj = reference.get_object()
                    if obj.get("/Subtype") == "/Form":
                        stream_size(obj)
                        resources(obj, depth + 1)
        active.remove(id(node))
        resource_done.add(id(node))

    for page in pages:
        contents = page.get("/Contents")
        if contents is not None:
            contents = contents.get_object()
            streams = contents if isinstance(contents, ArrayObject) else [contents]
            for reference in streams:
                stream_size(reference.get_object())
        resources(page)


def extract_pdf(response: Response, *, metadata: dict | None = None,
                quality_flags=(), limits: PDFLimits | None = None) -> Document:
    """Extract acquired PDF bytes under context-local parser limits."""
    limits = limits or PDFLimits()
    # XRef/object streams can be decoded during reader construction, before the
    # page-content preflight. Keep library limits scoped to this extraction.
    with apply_configuration(
        maximum_declared_stream_length=limits.max_bytes,
        array_based_stream_maximum_output_length=limits.max_stream_bytes,
        zlib_maximum_output_length=limits.max_stream_bytes,
        lzw_maximum_output_length=limits.max_stream_bytes,
        run_length_maximum_output_length=limits.max_stream_bytes,
        brotli_maximum_output_length=limits.max_stream_bytes,
        stream_decoding_work_maximum_length=limits.max_decoded_bytes,
        dictionary_maximum_element_count=4096,
        array_maximum_element_count=16384,
        page_tree_maximum_entries=10000,
        page_tree_maximum_depth=32,
        xform_maximum_invocations_per_extraction=1000,
        jbig2dec_binary=None,
        disable_legacy_handling=True,
    ):
        return _extract_pdf(response, metadata=metadata, quality_flags=quality_flags, limits=limits)


def _extract_pdf(response: Response, *, metadata: dict | None = None,
                quality_flags=(), limits: PDFLimits | None = None) -> Document:
    """Parse already acquired bytes; this primitive grants no source/rights approval.

    Sections preserve printed text page-by-page with ``page=N`` citation locators.
    Their headings are the first printed line, not inferred semantic PDF structure.
    Form widget values and links are never read, executed or submitted.
    """
    limits = limits or PDFLimits()
    if response.status != 200:
        raise PDFExtractionError(f"http-status: {response.status}")
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/pdf":
        raise PDFExtractionError("invalid-media-type")
    if len(response.body) > limits.max_bytes:
        raise PDFExtractionError("document-byte-limit")
    if not response.body.startswith(b"%PDF-"):
        raise PDFExtractionError("invalid-pdf-signature")
    try:
        reader = PdfReader(BytesIO(response.body), strict=True)
        if reader.is_encrypted:
            raise PDFExtractionError("encrypted-document")
        count = len(reader.pages)
        if count == 0:
            raise PDFExtractionError("empty-document")
        if count > limits.max_pages:
            raise PDFExtractionError("page-limit")
        _preflight_streams(reader.pages, limits)
        sections, flags, text_size = [], list(quality_flags), 0

        def visit(text, *_):
            nonlocal text_size
            text_size += len(text)
            if text_size > limits.max_text_chars:
                raise PDFExtractionError("text-character-limit")

        for number, page in enumerate(reader.pages, 1):
            raw = page.extract_text(visitor_text=visit)
            if text_size > limits.max_text_chars or len(raw) > limits.max_text_chars:
                raise PDFExtractionError("text-character-limit")
            lines = [clean_text(line) for line in raw.splitlines() if clean_text(line)]
            if not lines:
                flags.append(f"page-{number}-no-primary-text-ocr-unsupported")
                continue
            # No form values are interpreted: printed instructions and blank labels
            # remain literal source text, never invented completed-field facts.
            text = "\n".join(lines)
            sections.append(Section(
                lines[0][:200], text, f"page={number}", bool(EXCEPTION.search(text)),
                [{"kind": "text", "text": text}],
            ))
        if not sections:
            raise PDFExtractionError("no-primary-text-empty-or-scanned-ocr-unsupported")
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(f"invalid-or-unsupported-pdf: {type(exc).__name__}") from exc
    url = canonicalize(response.url)
    provenance = {
        "sourceIds": [], "topics": [], "documentType": "guidance",
        "rights": None, "legal": None, "language": None, **(metadata or {}),
        "schemaVersion": 2, "canonicalUrl": url, "sourceUrl": url,
        "mediaType": "application/pdf", "pageCount": count,
        "contentHashBasis": "original-response-bytes",
    }
    validate_metadata(provenance)
    document = Document(
        url, sections[0].heading, response.checked_at, None,
        response.digest, response.digest,
        "quarantined" if flags else "review-required", sorted(set(flags)), sections, [],
        list(response.aliases), extraction_method=PDF_EXTRACTION_METHOD, metadata=provenance,
    )
    document.extraction_hash = extraction_digest(document)
    return document
