"""Conservative robots parser with longest-match, wildcard, and group handling."""

from dataclasses import dataclass
import math
import re
from urllib.parse import urlsplit

from .policy import AcquisitionError


@dataclass(frozen=True)
class RobotsPolicy:
    rules: tuple[tuple[bool, str], ...]
    delay: float = 1.0

    def allows(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        matches = []
        for allow, pattern in self.rules:
            if not pattern:
                continue
            anchored = pattern.endswith("$")
            core = pattern[:-1] if anchored else pattern
            expression = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if anchored else "")
            if re.search(expression, path):
                matches.append((len(core.replace("*", "")), allow))
        return max(matches, default=(0, True))[1]


def parse_robots(body: bytes, content_type: str, agent: str = "BCPilotIngest") -> RobotsPolicy:
    if content_type.split(";")[0].strip().lower() != "text/plain":
        raise AcquisitionError("Robots policy is not text/plain; fail closed")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise AcquisitionError("Robots policy is not valid UTF-8") from exc
    if "<" in text or not text.strip():
        raise AcquisitionError("Empty/HTML robots policy; fail closed")
    groups: list[tuple[list[str], list[tuple[bool, str]], float]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    delay = 1.0
    started_rules = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise AcquisitionError("Malformed robots directive")
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if started_rules:
                groups.append((agents, rules, delay))
                agents, rules, delay, started_rules = [], [], 1.0, False
            if not value or not re.fullmatch(r"[\w*.-]+", value):
                raise AcquisitionError("Invalid robots user-agent")
            agents.append(value.lower())
        elif key in ("allow", "disallow", "crawl-delay"):
            if not agents:
                raise AcquisitionError("Robots rules without a user-agent")
            started_rules = True
            if key == "crawl-delay":
                try:
                    parsed_delay = float(value)
                except ValueError as exc:
                    raise AcquisitionError("Invalid crawl-delay") from exc
                if not math.isfinite(parsed_delay) or not 0 <= parsed_delay <= 3600:
                    raise AcquisitionError("Unsupported crawl-delay")
                delay = max(1.0, parsed_delay)
            else:
                if value and not value.startswith(("/", "*")):
                    raise AcquisitionError("Invalid robots path")
                rules.append((key == "allow", value))
        elif key in ("sitemap", "host", "request-rate", "clean-param"):
            if key == "request-rate":
                # Do not silently ignore a publisher rate stricter than our interpretation.
                raise AcquisitionError("Publisher request-rate requires manual policy review")
        else:
            # Unknown extensions do not override recognized standard access rules.
            continue
    if agents:
        groups.append((agents, rules, delay))
    if not groups:
        raise AcquisitionError("No robots user-agent policy found")
    selected = []
    for names, group_rules, group_delay in groups:
        score = max(
            (0 if n == "*" else len(n) for n in names if n == "*" or n in agent.lower()),
            default=-1,
        )
        if score >= 0:
            selected.append((score, group_rules, group_delay))
    if not selected:
        raise AcquisitionError("No policy applicable to this crawler; review required")
    score = max(g[0] for g in selected)
    return RobotsPolicy(
        tuple(rule for s, rs, _ in selected if s == score for rule in rs),
        max(d for s, _, d in selected if s == score),
    )
