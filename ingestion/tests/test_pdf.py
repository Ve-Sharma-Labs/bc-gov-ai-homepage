"""Synthetic in-memory PDF fixtures; no publisher, OCR or index requests."""

from copy import deepcopy
import hashlib
from io import BytesIO
import unittest
import zlib

from pypdf import PdfWriter, get_configuration
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, NameObject,
    NumberObject, TextStringObject,
)

from bc_ingestion.extract import chunk_document, extract
from bc_ingestion.fetch import Response
from bc_ingestion.metadata import validate_metadata
from bc_ingestion.pdf import PDFExtractionError, PDFLimits, extract_pdf
from bc_ingestion.pipeline import restore_document
from bc_ingestion.policy import AcquisitionError


URL = "https://www2.gov.bc.ca/gov/content/synthetic-only/guide.pdf"


def pdf_bytes(pages, *, encrypted=False, compressed=False, field=False, scanned=False):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        if scanned:
            image = DecodedStreamObject()
            image.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            })
            image.set_data(b"\x00\x00\x00")
            page["/Resources"][NameObject("/XObject")] = DictionaryObject({
                NameObject("/Scan"): writer._add_object(image),
            })
            stream = DecodedStreamObject()
            stream.set_data(b"q 500 0 0 700 20 20 cm /Scan Do Q")
            page[NameObject("/Contents")] = writer._add_object(stream)
        if lines:
            stream = DecodedStreamObject()
            commands = ["BT /F1 12 Tf 50 750 Td"]
            for line in lines:
                escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                commands.append(f"({escaped}) Tj 0 -20 Td")
            commands.append("ET")
            stream.set_data("\n".join(commands).encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(
                stream.flate_encode() if compressed else stream
            )
        if field:
            widget = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject("Applicant"),
                NameObject("/V"): TextStringObject("SYNTHETIC PRIVATE WIDGET VALUE"),
                NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (10, 10, 100, 30)]),
            })
            ref = writer._add_object(widget)
            page[NameObject("/Annots")] = ArrayObject([ref])
            writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
                NameObject("/Fields"): ArrayObject([ref]),
            })
    if encrypted:
        writer.encrypt("synthetic-password")
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def response(body, media="application/pdf"):
    return Response(URL, 200, {"content-type": media}, body, "2026-11-23T00:00:00Z")


class PDFTests(unittest.TestCase):
    def test_reader_construction_limits_compressed_xref_and_restores_configuration(self):
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length 34 >>\nstream\nBT /F1 12 Tf (Instructions) Tj ET\nendstream",
        ]
        body, offsets = b"%PDF-1.5\n", [0]
        for number, obj in enumerate(objects, 1):
            offsets.append(len(body))
            body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
        offsets.append(len(body))
        entries = b"\x00\x00\x00\x00\x00\xff\xff"
        entries += b"".join(b"\x01" + offset.to_bytes(4) + b"\x00\x00" for offset in offsets[1:])
        compressed = zlib.compress(entries + b"\x00" * 10000)
        body += (
            f"6 0 obj\n<< /Type /XRef /Size 7 /Root 1 0 R /W [1 4 2] "
            f"/Filter /FlateDecode /Length {len(compressed)} >>\nstream\n".encode()
            + compressed + b"\nendstream\nendobj\n"
            + f"startxref\n{offsets[-1]}\n%%EOF\n".encode()
        )
        before = get_configuration()
        self.assertIn("Instructions", extract_pdf(response(body)).sections[0].text)
        with self.assertRaises(PDFExtractionError) as caught:
            extract_pdf(response(body), limits=PDFLimits(max_stream_bytes=1000))
        self.assertEqual(caught.exception.reason, "invalid-or-unsupported-pdf: PdfReadError")
        self.assertEqual(get_configuration(), before)

    def test_primary_text_page_citations_dispatch_and_original_byte_hash(self):
        body = pdf_bytes([
            ["Application instructions", "Bring the listed documents."],
            ["Exceptions", "You must not submit original identification."],
        ], compressed=True)
        document = extract(response(body, "Application/PDF; charset=binary"))
        self.assertEqual(document.quality, "review-required")
        self.assertEqual([s.heading for s in document.sections], ["Application instructions", "Exceptions"])
        self.assertEqual([s.locator for s in document.sections], ["page=1", "page=2"])
        self.assertIn("Bring the listed documents.", document.sections[0].text)
        self.assertTrue(document.sections[1].contains_exceptions)
        self.assertEqual(document.content_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual(document.response_hash, document.content_hash)
        self.assertEqual(document.metadata["schemaVersion"], 2)
        self.assertEqual(document.metadata["pageCount"], 2)
        self.assertIsNone(document.publisher_updated_at)
        self.assertEqual(restore_document(document.to_dict()).to_dict(), document.to_dict())
        self.assertEqual(chunk_document(document)[0]["locators"], ["page=1", "page=2"])
        changed = extract_pdf(response(body + b"\n% original byte change\n"))
        self.assertNotEqual(document.content_hash, changed.content_hash)
        self.assertNotEqual(document.extraction_hash, changed.extraction_hash)

    def test_invalid_media_signature_document_and_legacy_schema_are_rejected(self):
        body = pdf_bytes([["Guide", "Read the instructions."]])
        for fetched in (
            response(body, "text/html"), response(body, ""),
            response(b"not a PDF"), response(b"%PDF-1.7\nbroken"),
        ):
            with self.subTest(media=fetched.headers, body=fetched.body[:12]):
                with self.assertRaises(PDFExtractionError):
                    extract_pdf(fetched)
        metadata = deepcopy(extract_pdf(response(body)).metadata)
        metadata["schemaVersion"] = 1
        metadata.pop("pageCount")
        metadata.pop("contentHashBasis")
        with self.assertRaises(AcquisitionError):
            validate_metadata(metadata)

    def test_empty_scanned_and_encrypted_documents_fail_with_reasons(self):
        for body, reason in (
            (pdf_bytes([]), "empty-document"),
            (pdf_bytes([[]]), "no-primary-text-empty-or-scanned-ocr-unsupported"),
            (pdf_bytes([[]], scanned=True), "no-primary-text-empty-or-scanned-ocr-unsupported"),
            (pdf_bytes([["Guide"]], encrypted=True), "encrypted-document"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(PDFExtractionError) as caught:
                    extract_pdf(response(body))
                self.assertEqual(caught.exception.reason, reason)
        partial = extract_pdf(response(pdf_bytes([["Instructions", "Read this page."], []])))
        self.assertEqual(partial.quality, "quarantined")
        self.assertEqual(partial.flags, ["page-2-no-primary-text-ocr-unsupported"])
        self.assertEqual(len(partial.sections), 1)

    def test_byte_page_text_and_decoded_stream_limits_fail_without_truncation(self):
        body = pdf_bytes([["Guide", "A" * 1000], ["Second page"]], compressed=True)
        for limits, reason in (
            (PDFLimits(max_bytes=len(body) - 1), "document-byte-limit"),
            (PDFLimits(max_pages=1), "page-limit"),
            (PDFLimits(max_text_chars=20), "text-character-limit"),
            (PDFLimits(max_stream_bytes=100), "decoded-stream-byte-limit"),
            (PDFLimits(max_decoded_bytes=100), "total-decoded-byte-limit"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(PDFExtractionError) as caught:
                    extract_pdf(response(body), limits=limits)
                self.assertEqual(caught.exception.reason, reason)
        with self.assertRaises(PDFExtractionError):
            PDFLimits(max_pages=101)

    def test_downloadable_form_preserves_printed_blanks_not_widget_values(self):
        document = extract_pdf(response(pdf_bytes([
            ["Application form", "Name: __________", "Use this form to prepare your application."],
        ], field=True)))
        self.assertEqual(document.quality, "review-required")
        self.assertIn("Name: __________", document.sections[0].text)
        self.assertNotIn("SYNTHETIC PRIVATE WIDGET VALUE", str(document.to_dict()))
        self.assertEqual(document.links, [])

    def test_resource_expansion_repeated_streams_and_unsupported_filters(self):
        body = pdf_bytes([["Guide", "Printed instructions."]])
        for scenario, reason in (
            ("font", "decoded-stream-byte-limit"),
            ("repeat", "total-decoded-byte-limit"),
            ("filter", "unsupported-content-stream-filter"),
        ):
            writer = PdfWriter(clone_from=BytesIO(body))
            page = writer.pages[0]
            content = page["/Contents"]
            if scenario == "font":
                cmap = DecodedStreamObject()
                cmap.set_data(b"A" * 1000)
                page["/Resources"]["/Font"]["/F1"][NameObject("/ToUnicode")] = writer._add_object(
                    cmap.flate_encode()
                )
                limits = PDFLimits(max_stream_bytes=200)
            elif scenario == "repeat":
                reference = writer._add_object(content)
                page[NameObject("/Contents")] = ArrayObject([reference] * 30)
                limits = PDFLimits(max_decoded_bytes=200)
            else:
                content[NameObject("/Filter")] = NameObject("/ASCII85Decode")
                limits = PDFLimits()
            result = BytesIO()
            writer.write(result)
            with self.subTest(scenario=scenario):
                with self.assertRaises(PDFExtractionError) as caught:
                    extract_pdf(response(result.getvalue()), limits=limits)
                self.assertEqual(caught.exception.reason, reason)


if __name__ == "__main__":
    unittest.main()
