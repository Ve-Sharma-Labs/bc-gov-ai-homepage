"""This policy must be published in the trusted, versioned Foundry prompt agent."""

from bc_api.jurisdiction import JurisdictionPack, current_pack, load_jurisdiction, read_json


def general_instructions(pack: JurisdictionPack | None = None) -> str:
    pack = pack or current_pack()
    return (
        pack.prompt("agent")
        + pack.prompt("general")
        + "\n".join(pack.prompt("dialogue").splitlines()[1:])
    )


AGENT_INSTRUCTIONS = current_pack().prompt("agent")
GENERAL_INSTRUCTIONS = general_instructions()
# Compatibility exports for existing BC tooling; SK never registers these journeys.
JOURNEY_POLICIES = read_json(
    load_jurisdiction("bc").root / "jurisdictions" / "bc" / "flows" / "registry.json"
)["journeyPolicies"] if current_pack().id == "bc" else {}
LOCATION_JOURNEYS = frozenset({"licence-renewal", "rental-assistance", "service-bc"})


def instructions_for(
    journey_id: str | None, pack: JurisdictionPack | None = None
) -> str:
    pack = pack or current_pack()
    if journey_id is None:
        return pack.prompt("agent")
    if not pack.guided_journeys or pack.id != "bc":
        raise ValueError("This jurisdiction does not register guided journey instructions.")
    policies = read_json(
        pack.root / "jurisdictions" / pack.id / "flows" / "registry.json"
    )["journeyPolicies"]
    return (
        pack.prompt("agent")
        + f"\nYour assigned journey is {journey_id}. "
        + policies[journey_id]
        + f"\nUse only {journey_id} for preparation-plan and scoped search tool arguments. "
        "Ask for clarification or direct the person to another supported journey "
        "rather than crossing your scope."
    )
