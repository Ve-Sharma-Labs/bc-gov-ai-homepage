"""Dataset-specific, candidate-only acquisition for licensed Service BC offices."""

import hashlib
import json
import math
from urllib.parse import urlsplit

from .fetch import USER_AGENT, Response, transport, utc_now
from .metadata import digest
from .policy import AcquisitionError

PACKAGE_ID = "2b44d212-5438-47a9-ad23-20eb8ada9709"
PACKAGE_NAME = "service-bc-office-locations"
RESOURCE_ID = "c7cc9297-220c-4d6c-a9a7-72d0680b2f74"
PACKAGE_URL = (
    f"https://catalogue.data.gov.bc.ca/api/3/action/package_show?id={PACKAGE_NAME}"
)
RECORDS_URL = (
    "https://catalogue.data.gov.bc.ca/api/3/action/datastore_search"
    f"?resource_id={RESOURCE_ID}&limit=100"
)
LICENCE_TITLE = "Open Government Licence - British Columbia"
LICENCE_URL = "https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61"
REQUIRED_FIELDS = {
    "_id",
    "External Site",
    "Address",
    "Locality",
    "Site_Phone_No",
    "Site_Fax_no",
    "Website_URL",
    "Site_Email",
    "Latitude",
    "Longitude",
    "Office Code",
}
EXPECTED_FIELD_TYPES = {
    "_id": "int",
    "External Site": "text",
    "Address": "text",
    "Locality": "text",
    "Site_Phone_No": "text",
    "Site_Fax_no": "text",
    "Website_URL": "text",
    "Site_Email": "text",
    "Latitude": "numeric",
    "Longitude": "numeric",
    "Office Code": "numeric",
}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AcquisitionError("Open-data JSON contains duplicate object keys")
        value[key] = item
    return value


def _json_response(response: Response, expected_url: str) -> dict:
    if response.url != expected_url or response.status != 200:
        raise AcquisitionError(
            "Open-data endpoint did not return the exact successful request"
        )
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in ("application/json", "text/json"):
        raise AcquisitionError("Open-data endpoint did not return JSON")
    try:
        value = json.loads(response.body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError("Open-data endpoint returned malformed JSON") from exc
    if not isinstance(value, dict) or value.get("success") is not True:
        raise AcquisitionError(
            "Open-data endpoint did not return a successful CKAN result"
        )
    return value


def _text(value, field: str, *, required=True, maximum=2000) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise AcquisitionError(f"Open-data {field} must be text")
    value = " ".join(value.split())
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise AcquisitionError(f"Open-data {field} is empty or out of bounds")
    return value


def _optional_text(value, field: str, *, maximum=2000) -> str:
    value = _text(value, field, required=False, maximum=maximum)
    return "" if value.casefold() in {"none", "null", "n/a", "not available"} else value


def _coordinate(value, field: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise AcquisitionError(f"Open-data {field} must be a finite number")
    value = float(value)
    if not minimum <= value <= maximum:
        raise AcquisitionError(f"Open-data {field} is outside British Columbia bounds")
    return value


def build_service_bc_candidate(
    package_response: Response,
    records_response: Response,
    *,
    checked_at: str | None = None,
) -> dict:
    package_envelope = _json_response(package_response, PACKAGE_URL)
    records_envelope = _json_response(records_response, RECORDS_URL)
    package = package_envelope.get("result")
    if not isinstance(package, dict) or (
        package.get("id") != PACKAGE_ID
        or package.get("name") != PACKAGE_NAME
        or package.get("license_title") != LICENCE_TITLE
        or package.get("license_url") != LICENCE_URL
        or package.get("private") is not False
        or package.get("publish_state") != "PUBLISHED"
        or package.get("security_class") != "PUBLIC"
        or package.get("view_audience") != "Public"
        or package.get("download_audience") != "Public"
    ):
        raise AcquisitionError(
            "Service BC dataset identity, licence or public status changed"
        )
    resources = package.get("resources")
    if not isinstance(resources, list):
        raise AcquisitionError("Service BC dataset resources are missing")
    resource = next(
        (
            item
            for item in resources
            if isinstance(item, dict) and item.get("id") == RESOURCE_ID
        ),
        None,
    )
    if (
        resource is None
        or resource.get("datastore_active") is not True
        or resource.get("package_id") != PACKAGE_ID
    ):
        raise AcquisitionError(
            "The reviewed Service BC DataStore resource is unavailable"
        )

    result = records_envelope.get("result")
    if not isinstance(result, dict) or result.get("resource_id") != RESOURCE_ID:
        raise AcquisitionError("Service BC records came from an unexpected resource")
    raw_records, fields = result.get("records"), result.get("fields")
    if (
        not isinstance(raw_records, list)
        or not isinstance(fields, list)
        or type(result.get("total")) is not int
        or result["total"] != len(raw_records)
        or not 1 <= len(raw_records) <= 100
    ):
        raise AcquisitionError("Service BC DataStore result is incomplete or unbounded")
    field_types = {
        item.get("id"): item.get("type")
        for item in fields
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not REQUIRED_FIELDS <= set(field_types) or any(
        field_types.get(name) != expected
        for name, expected in EXPECTED_FIELD_TYPES.items()
    ):
        raise AcquisitionError("Service BC DataStore schema is missing reviewed fields")

    offices, identifiers = [], set()
    for row in raw_records:
        if not isinstance(row, dict):
            raise AcquisitionError("Service BC DataStore record must be an object")
        office_code = row.get("Office Code")
        if type(office_code) not in (int, float) or not float(office_code).is_integer():
            raise AcquisitionError("Service BC office code must be an integer")
        office_code = str(int(office_code))
        if office_code in identifiers:
            raise AcquisitionError("Duplicate Service BC office code")
        identifiers.add(office_code)
        website = _optional_text(row.get("Website_URL"), "website", maximum=1000)
        if website and (
            urlsplit(website).scheme not in ("http", "https")
            or not urlsplit(website).hostname
            or urlsplit(website).username
            or urlsplit(website).password
        ):
            raise AcquisitionError(
                "Service BC office website is not a public HTTP(S) URL"
            )
        offices.append(
            {
                "officeCode": office_code,
                "name": _text(row.get("External Site"), "office name", maximum=500),
                "address": _text(row.get("Address"), "address", maximum=1000),
                "locality": _text(row.get("Locality"), "locality", maximum=200),
                "phone": _optional_text(row.get("Site_Phone_No"), "phone", maximum=100),
                "fax": _optional_text(row.get("Site_Fax_no"), "fax", maximum=100),
                "email": _optional_text(row.get("Site_Email"), "email", maximum=200),
                "website": website,
                "latitude": _coordinate(row.get("Latitude"), "latitude", 47, 61),
                "longitude": _coordinate(row.get("Longitude"), "longitude", -140, -110),
            }
        )
    offices.sort(key=lambda item: (item["locality"].casefold(), item["officeCode"]))
    checked_at = checked_at or utc_now()
    dataset = {
        "id": package["id"],
        "name": package["name"],
        "title": _text(package.get("title"), "dataset title", maximum=500),
        "recordLastModified": _text(
            package.get("record_last_modified"), "record last modified", maximum=40
        ),
        "dataQuality": _text(package.get("data_quality"), "data quality", maximum=500),
        "resourceId": RESOURCE_ID,
        "resourceLastModified": resource.get("last_modified"),
    }
    rights = {
        "status": "dataset-specific-open-licence",
        "licenceTitle": LICENCE_TITLE,
        "licenceUrl": LICENCE_URL,
        "evidenceUrl": f"https://catalogue.data.gov.bc.ca/dataset/{PACKAGE_ID}",
    }
    candidate = {
        "schemaVersion": 1,
        "mode": "candidate-only",
        "sourceId": "service-bc",
        "checkedAt": checked_at,
        "dataset": dataset,
        "rights": rights,
        "records": offices,
        "recordCount": len(offices),
        "responseHashes": {
            "package": hashlib.sha256(package_response.body).hexdigest(),
            "records": hashlib.sha256(records_response.body).hexdigest(),
        },
        "contentHash": digest(offices),
        "reviewFlags": [
            "office-service-capabilities-not-included",
            "published-hours-not-included",
            "datastore-resource-date-review-required",
            *(
                ["legacy-http-office-links-present"]
                if any(item["website"].startswith("http://") for item in offices)
                else []
            ),
            *(
                ["missing-contact-fields-present"]
                if any(
                    not item["phone"] or not item["fax"] or not item["email"]
                    for item in offices
                )
                else []
            ),
        ],
        "publicationApproved": False,
        "notice": (
            "Licensed candidate data only. It can expand office identity/contact/location review, "
            "but it does not prove service capabilities, current hours or live availability."
        ),
    }
    candidate["reviewHash"] = digest(candidate)
    return candidate


def acquire_service_bc_candidate() -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Accept": "application/json",
    }
    package = transport(PACKAGE_URL, limit=2_000_000, timeout=25, headers=headers)
    records = transport(RECORDS_URL, limit=4_000_000, timeout=25, headers=headers)
    return build_service_bc_candidate(package, records)
