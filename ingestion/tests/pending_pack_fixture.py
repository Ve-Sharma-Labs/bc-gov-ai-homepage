"""Synthetic pending policy for offline tests, independent of the live SK pack."""

import json
from pathlib import Path
from unittest.mock import patch


def pending_saskatchewan_pack():
    root = Path(__file__).resolve().parents[2] / "jurisdictions" / "sk"
    manifest_path = root / "jurisdiction.json"
    programme_path = root / "content" / "source-programme.json"
    original = Path.read_text

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path.resolve() == manifest_path:
            value = json.loads(text)
            value["researchHosts"] = ["www.saskatchewan.ca"]
            value["sourcePolicy"]["approvalStatus"] = "pending-rag-permission"
            value["sourcePolicy"].pop("operationReview", None)
            return json.dumps(value)
        if path.resolve() == programme_path:
            value = json.loads(text)
            value["publicationPolicy"] = "exact-hash-human-review"
            value["sources"] = [source for source in value["sources"]
                                if source["host"] == "www.saskatchewan.ca"]
            value["accessObservations"] = [item for item in value["accessObservations"]
                                          if item["host"] == "www.saskatchewan.ca"]
            return json.dumps(value)
        return text

    return patch.object(Path, "read_text", read)
