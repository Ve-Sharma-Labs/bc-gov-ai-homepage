"""Model-selectable passages; the application renders their original words and links."""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from bc_api.errors import ApiError
from bc_api.models import Evidence

SENTENCE_BOUNDARY = re.compile(r"""(?<=[.!?])["”']?\s+|\n+""")
QUOTE_MARKER = re.compile(r"\{\{quote:([a-f0-9]{12})\}\}")


def normalize_quote(value: str) -> str:
    value = value.translate({0x2018: ord("'"), 0x2019: ord("'")})
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\s+([,;:!?])", r"\1", value)
    return " ".join(value.strip(' \t\r\n*>"“”').split()).rstrip(".").casefold()


@dataclass(frozen=True)
class SourceQuote:
    text: str
    url: str
    title: str


def quote_registry(evidence: Iterable[Evidence]) -> dict[str, SourceQuote]:
    result: dict[str, SourceQuote] = {}
    for item in evidence:
        for sentence in SENTENCE_BOUNDARY.split(item.content):
            sentence = sentence.strip()
            if not 20 <= len(sentence) <= 1500 or not sentence.endswith("."):
                continue
            quote = SourceQuote(sentence, item.reference.url, item.reference.title)
            key = hashlib.sha256(f"{quote.url}\n{quote.text}".encode()).hexdigest()[:12]
            if key in result and result[key] != quote:
                raise ApiError(503, "SOURCE_CONFLICT", "The source passage identifiers conflict.")
            result[key] = quote
    return result


def mark_source_quotes(content: str, url: str, quotes: dict[str, SourceQuote]) -> str:
    for key, quote in quotes.items():
        if quote.url == url:
            content = content.replace(quote.text, "{{quote:" + key + "}} " + quote.text)
    return content


def expand_source_quotes(text: str, quotes: dict[str, SourceQuote]) -> str:
    matches = list(QUOTE_MARKER.finditer(text))
    if len(matches) > 8:
        raise ApiError(502, "OUTPUT_LIMIT", "Too many source passages were requested.")
    if "{{quote:" in QUOTE_MARKER.sub("", text):
        raise ApiError(502, "CITATION_INVALID", "An unknown source passage was withheld.")

    def replace(match: re.Match[str]) -> str:
        quote = quotes.get(match[1])
        if quote is None:
            raise ApiError(502, "CITATION_INVALID", "An unknown source passage was withheld.")
        title = re.sub(r"[][()<>`!*_\\]", "", quote.title)
        return f"\n\n{quote.text}\n[{title}]({quote.url})\n\n"

    return QUOTE_MARKER.sub(replace, text)
