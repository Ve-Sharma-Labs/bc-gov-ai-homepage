"""Read bounded JSON members without extracting an artifact to the filesystem."""

import json
import sys
import zipfile

LIMIT = 1_000_000

try:
    with zipfile.ZipFile(sys.argv[1]) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 3:
            raise ValueError("Invalid archive")
        if set(names) - {"report.json", "candidate.json", "qualification.json"}:
            raise ValueError("Unexpected archive member")
        result = {}
        for name in ("report.json", "candidate.json"):
            info = archive.getinfo(name)
            if info.file_size > LIMIT or info.flag_bits & 1:
                raise ValueError("Oversized or encrypted member")
            with archive.open(info) as member:
                content = member.read(LIMIT + 1)
            if len(content) > LIMIT:
                raise ValueError("Oversized content")
            result[name] = json.loads(content)
        print(json.dumps(result))
except (OSError, ValueError, KeyError, zipfile.BadZipFile):
    print("INVALID_PYRIT_ARTIFACT", file=sys.stderr)
    raise SystemExit(1) from None
