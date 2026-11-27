"""Recognize a reviewed source's internally inconsistent renewal payments."""

import re
from collections.abc import Iterable
from decimal import Decimal

from bc_api.models import Evidence

SGI_RENEWAL_URL = "https://sgi.sk.ca/renew-licence"
_AMOUNT = r"\d{1,6}(?:\.\d{1,2})?"
_INSTALLMENTS = re.compile(
    rf"\bthe total (?:will be|is) \$(?P<total>{_AMOUNT}):\s*"
    rf"\$(?P<first>{_AMOUNT}) in year 1,\s*and\s*"
    rf"\$(?P<later>{_AMOUNT}) in years 2 (?:through|to) (?P<last>\d{{1,2}})\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"[$\u00a3\u20ac\u00a5]\s*\d|\b(?:CAD|dollars?)\b", re.IGNORECASE)


def inconsistent_sgi_renewal(item: Evidence) -> bool:
    if item.reference.source_id != "sk-sgi-content" or item.reference.url != SGI_RENEWAL_URL:
        return False
    for match in _INSTALLMENTS.finditer(item.content):
        last = int(match["last"])
        if 2 <= last <= 99 and Decimal(match["total"]) != (
            Decimal(match["first"]) + Decimal(match["later"]) * (last - 1)
        ):
            return True
    return False


def contains_money(text: str) -> bool:
    return bool(_MONEY.search(text))


def sgi_renewal_fee_conflict(query: str, items: Iterable[Evidence]) -> Evidence | None:
    if not (
        re.search(r"\b(?:driv(?:er(?:['\u2019]?s)?|ing)|sgi)\b", query, re.IGNORECASE)
        and re.search(r"\blicen[cs](?:e|es|ing)\b", query, re.IGNORECASE)
        and re.search(r"\brenew(?:al|ing|ed|s)?\b", query, re.IGNORECASE)
        and re.search(
            r"\b(?:fees?|costs?|prices?|payments?|pay|paying|charges?|how much)\b",
            query,
            re.IGNORECASE,
        )
    ):
        return None
    return next((item for item in items if inconsistent_sgi_renewal(item)), None)
