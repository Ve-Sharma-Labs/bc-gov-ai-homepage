"""Extract a deliberately reviewed municipality subset from the Service BC table."""

import re
from bs4 import BeautifulSoup

from .extract import clean_text
from .policy import AcquisitionError, SERVICE_BC, canonicalize


SERVICE_KEYS = ("icbc-licensing", "income-assistance", "bc-services-card", "bceid")
LABELS = {
    "icbc-licensing": re.compile(r"ICBC\s+driver\s+licensing", re.I),
    "income-assistance": re.compile(r"income(?:\s+and\s+disability)?\s+assistance", re.I),
    "bc-services-card": re.compile(r"BC\s+Services\s+Card\s+(?:account|identity)", re.I),
    "bceid": re.compile(r"\bBCeID\b", re.I),
}


def parse_service_bc_offices(html: bytes, url: str, checked_at: str, municipalities: list[str]) -> list[dict]:
    if canonicalize(url) != "https://www2.gov.bc.ca" + SERVICE_BC:
        raise AcquisitionError("Office facts must come from the reviewed canonical Service BC page")
    soup = BeautifulSoup(html, "html.parser")
    table = next((
        t for t in soup.find_all("table")
        if t.find("thead") and all(
            word in t.find("thead").get_text(" ", strip=True).lower()
            for word in ("location", "address", "hours", "more information")
        )
    ), None)
    if table is None:
        raise AcquisitionError("Expected publisher office table is missing")
    # The table explicitly links #services to the publisher's Popular services
    # group. Require the group and its labels; a blank cell inherits nothing.
    group_anchor = soup.find(id="services")
    group_text = ""
    if group_anchor:
        for node in group_anchor.find_all_next():
            if node.name == "table":
                break
            if node.name in ("p", "li", "h2", "h3"):
                group_text += " " + node.get_text(" ", strip=True)
    group = {key for key, pattern in LABELS.items() if pattern.search(group_text)}
    offices, found = [], set()
    for row in table.find_all("tr"):
        header = row.find("th", scope="row")
        cells = row.find_all("td", recursive=False)
        if not header or len(cells) != 3:
            continue
        city = clean_text(header.get_text(" ", strip=True))
        if city not in municipalities:
            continue
        if city in found:
            raise AcquisitionError("Duplicate municipality rows need manual disambiguation")
        found.add(city)
        address_node = cells[0].find("a", href=re.compile(r"^https://"))
        address = clean_text(address_node.get_text(" ", strip=True)) if address_node else ""
        hours = clean_text(cells[1].get_text(" ", strip=True))
        info = clean_text(cells[2].get_text(" ", strip=True))
        if not address or not hours or not info:
            raise AcquisitionError(f"Incomplete publisher office details for {city}")
        excluded_text = re.split(r"Not available at this location\s*:", info, flags=re.I)
        included_text = excluded_text[0]
        excluded = {
            key for key, pattern in LABELS.items()
            if len(excluded_text) > 1 and pattern.search(excluded_text[1])
        }
        included = {key for key, pattern in LABELS.items() if pattern.search(included_text)}
        if cells[2].find("a", href="#services") and re.search(
            r"This office offers the following services", included_text, re.I
        ):
            included |= group
        if re.search(r"only offers the following services", included_text, re.I):
            # This is an explicit closed list, not an inference from missing data.
            excluded |= set(SERVICE_KEYS) - included
        included -= excluded
        offices.append({
            "id": "service-bc-" + re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-"),
            "name": f"Service BC Centre {city}",
            "municipality": city,
            "address": address,
            "hours": hours,
            "services": sorted(included),
            "excludedServices": sorted(excluded),
            "sourceIds": ["service-bc"],
            "checkedAt": checked_at,
        })
    if found != set(municipalities):
        raise AcquisitionError("One or more requested municipalities were not found in the office table")
    return offices
