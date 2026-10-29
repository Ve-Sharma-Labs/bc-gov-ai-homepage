import pytest
from pydantic import TypeAdapter, ValidationError

from bc_api.agents import route_journey
from bc_api.errors import ApiError
from bc_api.input import parse_options, validate_run
from bc_api.models import (
    SCREENING_NOTICE,
    ApplicationPreview,
    Artifact,
    ArtifactList,
    AuditReceipt,
    Capabilities,
    ConsentProposal,
    ConsentReceipt,
    ConsentRequest,
    ConsentRevocation,
    ContextFact,
    DemoPersonaSummary,
    ProgramMatch,
    ProgramMatches,
)
from bc_api.protocol import validate_artifact

NOW = "2026-10-28T20:00:00Z"
LATER = "2026-10-28T20:30:00Z"


def match_payload(program_id: str = "workbc-navigation") -> dict:
    return {
        "programId": program_id,
        "status": "potential-match",
        "ruleId": "workbc-screening",
        "ruleVersion": "2026-10-28.1",
        "policyEffectiveDate": "2026-10-28",
        "satisfiedConditions": ["bc-resident", "employment-ended"],
        "missingFacts": ["preferred-service-channel"],
        "disqualifyingFacts": [],
        "sourceIds": ["workbc"],
        "sourceVersions": [{"sourceId": "workbc", "version": "2026-10-28"}],
        "notice": SCREENING_NOTICE,
    }


def preview_payload() -> dict:
    return {
        "previewId": "preview-sam-1",
        "flowId": "job-loss",
        "schemaVersion": 1,
        "fields": [
            {
                "field": "employment-status",
                "label": "Employment status",
                "value": "recently-ended",
                "source": "synthetic-record",
                "sourceFactKey": "employment.status",
                "editable": True,
                "sensitivity": "protected-b",
                "requiresConfirmation": True,
            }
        ],
        "missingItems": ["Confirm the preferred service channel"],
        "submissionEnabled": False,
        "requiresHumanReview": True,
        "expiresAt": LATER,
    }


def summary_payload() -> dict:
    return {
        "personaLabel": "Sam - recently lost a job",
        "synthetic": True,
        "purpose": "personalize-job-loss-navigation",
        "categories": ["employment-income"],
        "facts": [
            {
                "key": "employment.status",
                "label": "Employment status",
                "category": "employment-income",
                "displayValue": "Recently ended",
                "provenance": "synthetic-government-record",
                "verifiedAt": NOW,
                "mutableByCitizen": True,
                "usedBy": ["workbc-navigation"],
            }
        ],
        "missingFacts": ["preferred-service-channel"],
        "consentExpiresAt": LATER,
    }


def consent_request_payload() -> dict:
    return {
        "checkpointId": "checkpoint-sam-1",
        "previewId": "preview-sam-1",
        "purpose": "personalize-job-loss-navigation",
        "destinationName": "WorkBC",
        "destinationUrl": "https://www.workbc.ca/",
        "categoriesToShare": ["employment-income"],
        "fieldNamesToShare": ["employment-status"],
        "transferMode": "none",
        "reviewedByCitizen": False,
        "submissionEnabled": False,
    }


def audit_payload() -> dict:
    return {
        "receiptId": "audit-sam-1",
        "sessionRef": "session-sam-1",
        "personaLabel": "Sam - recently lost a job",
        "synthetic": True,
        "events": [
            {
                "eventId": "event-rule-1",
                "sequence": 1,
                "occurredAt": NOW,
                "action": "rule-evaluated",
                "category": None,
                "ruleId": "workbc-screening",
                "ruleVersion": "2026-10-28.1",
                "sourceIds": ["workbc"],
                "sourceVersions": [{"sourceId": "workbc", "version": "2026-10-28"}],
                "outcome": "potential-match",
            }
        ],
        "containsRawContextValues": False,
    }


def test_persona_and_context_fact_contracts_are_allowlisted_and_strict():
    persona = DemoPersonaSummary.model_validate(
        {
            "id": "sam-job-loss",
            "displayName": "Sam - recently lost a job",
            "summary": "A fictional job-loss navigation scenario.",
            "availableCategories": ["employment-income", "region-preferences"],
            "synthetic": True,
        }
    )
    assert persona.id == "sam-job-loss"
    fact = ContextFact.model_validate(
        {
            "key": "employment.status",
            "value": "recently-ended",
            "category": "employment-income",
            "source": "synthetic-employment-system",
            "provenance": "synthetic-government-record",
            "verifiedAt": NOW,
            "sensitivity": "protected-b",
            "consentScope": "employment.read",
            "mutableByCitizen": True,
        }
    )
    assert fact.consent_scope == "employment.read"

    with pytest.raises(ValidationError):
        DemoPersonaSummary.model_validate(
            {
                "id": "unknown-persona",
                "displayName": "Unknown",
                "summary": "Not allowlisted.",
                "availableCategories": ["employment-income"],
                "synthetic": True,
            }
        )
    forged = fact.model_dump(by_alias=True)
    forged["source"] = "employment-system"
    with pytest.raises(ValidationError):
        ContextFact.model_validate(forged)
    forged = fact.model_dump(by_alias=True)
    forged["consentScope"] = "identity.read"
    with pytest.raises(ValidationError):
        ContextFact.model_validate(forged)
    forged = fact.model_dump(by_alias=True)
    forged["rawRecord"] = {"unsafe": True}
    with pytest.raises(ValidationError):
        ContextFact.model_validate(forged)


def test_consent_contracts_enforce_scope_mapping_uniqueness_and_lifetime():
    proposal = ConsentProposal.model_validate(
        {
            "proposalId": "proposal-sam-1",
            "personaId": "sam-job-loss",
            "purpose": "personalize-job-loss-navigation",
            "noticeVersion": "1",
            "scopes": [
                {
                    "scope": "employment.read",
                    "category": "employment-income",
                    "reason": "Use the fictional job-loss status.",
                    "required": True,
                }
            ],
            "expiresAt": LATER,
            "synthetic": True,
        }
    )
    assert proposal.synthetic is True
    receipt = ConsentReceipt.model_validate(
        {
            "consentId": "consent-sam-1",
            "purpose": "personalize-job-loss-navigation",
            "scopes": ["employment.read"],
            "subjectHash": "non-reversible-reference",
            "noticeVersion": "1",
            "grantedAt": NOW,
            "expiresAt": LATER,
            "revokedAt": None,
        }
    )
    assert receipt.revoked_at is None
    revocation = ConsentRevocation.model_validate(
        {
            "revocationId": "revocation-sam-1",
            "consentId": receipt.consent_id,
            "revokedScopes": ["employment.read"],
            "revokedAt": LATER,
            "reason": "citizen-request",
        }
    )
    assert revocation.reason == "citizen-request"

    duplicate = proposal.model_dump(by_alias=True)
    duplicate["scopes"].append(duplicate["scopes"][0])
    with pytest.raises(ValidationError):
        ConsentProposal.model_validate(duplicate)
    expired = receipt.model_dump(by_alias=True)
    expired["expiresAt"] = NOW
    with pytest.raises(ValidationError):
        ConsentReceipt.model_validate(expired)


def test_program_match_and_preview_contracts_preserve_versions_and_provenance():
    match = ProgramMatch.model_validate(match_payload())
    assert match.status == "potential-match"
    assert TypeAdapter(ProgramMatches).validate_python([match])[0] == match
    with pytest.raises(ValidationError):
        TypeAdapter(ProgramMatches).validate_python([match, match])
    preview = ApplicationPreview.model_validate(preview_payload())
    assert preview.submission_enabled is False
    assert preview.requires_human_review is True

    mismatched_source = match_payload()
    mismatched_source["sourceVersions"][0]["sourceId"] = "different-source"
    with pytest.raises(ValidationError):
        ProgramMatch.model_validate(mismatched_source)
    overlapping = match_payload()
    overlapping["missingFacts"] = ["bc-resident"]
    with pytest.raises(ValidationError):
        ProgramMatch.model_validate(overlapping)
    enabled = preview_payload()
    enabled["submissionEnabled"] = True
    with pytest.raises(ValidationError):
        ApplicationPreview.model_validate(enabled)
    duplicate_field = preview_payload()
    duplicate_field["fields"].append(duplicate_field["fields"][0])
    with pytest.raises(ValidationError):
        ApplicationPreview.model_validate(duplicate_field)
    missing_with_value = preview_payload()
    missing_with_value["fields"][0]["source"] = "missing"
    with pytest.raises(ValidationError):
        ApplicationPreview.model_validate(missing_with_value)


def test_context_artifact_union_has_bounded_unique_server_identifiers(repository):
    preview = preview_payload()
    artifacts = [
        {
            "version": 1,
            "id": "artifact-summary-1",
            "kind": "context-summary",
            "payload": summary_payload(),
        },
        {
            "version": 1,
            "id": "artifact-matches-1",
            "kind": "program-matches",
            "payload": [match_payload()],
        },
        {
            "version": 1,
            "id": "artifact-preview-1",
            "kind": "application-preview",
            "payload": preview,
        },
        {
            "version": 1,
            "id": "artifact-consent-1",
            "kind": "consent-request",
            "payload": consent_request_payload(),
        },
        {
            "version": 1,
            "id": "artifact-audit-1",
            "kind": "audit-receipt",
            "payload": audit_payload(),
        },
    ]
    parsed = TypeAdapter(ArtifactList).validate_python(artifacts)
    assert [artifact.kind for artifact in parsed] == [
        "context-summary",
        "program-matches",
        "application-preview",
        "consent-request",
        "audit-receipt",
    ]
    duplicate = [*artifacts, {**artifacts[0]}]
    with pytest.raises(ValidationError):
        TypeAdapter(ArtifactList).validate_python(duplicate)
    with pytest.raises(ApiError, match="OUTPUT_INVALID"):
        validate_artifact(artifacts[0], repository)
    schema = TypeAdapter(Artifact).json_schema(by_alias=True)
    assert set(schema["discriminator"]["mapping"]) == {
        "preparation",
        "locations",
        "context-summary",
        "program-matches",
        "application-preview",
        "consent-request",
        "audit-receipt",
    }


def test_contextual_scope_is_versioned_server_owned_and_fails_closed(client, settings, run_input):
    assert parse_options({"bc": {"version": 3, "mode": "contextual-demo"}}).version == 3
    for options in (
        {"version": 3, "mode": "general"},
        {"version": 3, "mode": "contextual-demo", "journeyId": "service-bc"},
        {"version": 3, "mode": "contextual-demo", "researchRequested": True},
        {"version": 3, "mode": "contextual-demo", "facts": [{"key": "forged"}]},
    ):
        with pytest.raises(ApiError, match="CLIENT_CONTEXT_DENIED"):
            parse_options({"bc": options})

    run_input["forwardedProps"] = {"bc": {"version": 3, "mode": "contextual-demo"}}
    request = validate_run(run_input, settings)
    assert parse_options(request.forwarded_props).mode == "contextual-demo"
    for field, value in (
        ("tools", [{"name": "read_context"}]),
        ("context", [{"value": {"employment.status": "forged"}}]),
        ("state", {"personaFacts": {"employment.status": "forged"}}),
    ):
        with pytest.raises(ApiError, match="CLIENT_CONTEXT_DENIED"):
            validate_run({**run_input, field: value}, settings)
    with pytest.raises(ApiError, match="CONTEXTUAL_DEMO_UNAVAILABLE"):
        route_journey(request)
    response = client.post("/api/agent", json=run_input)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONTEXTUAL_DEMO_UNAVAILABLE"

    advertised = client.get("/api/capabilities")
    assert advertised.status_code == 200
    assert advertised.json()["requestVersions"] == [1, 2, 3]
    assert advertised.json()["syntheticContextAvailable"] is False
    assert advertised.json()["realIdentityIntegrated"] is False

    capabilities = Capabilities(
        mode="guided",
        ai_configured=False,
        message="Synthetic context is not enabled.",
    ).model_dump(by_alias=True)
    assert capabilities["requestVersions"] == [1, 2, 3]
    assert capabilities["syntheticContextAvailable"] is False
    assert capabilities["realIdentityIntegrated"] is False


def test_handoff_and_audit_contracts_cannot_claim_transfer_or_raw_values():
    request = ConsentRequest.model_validate(consent_request_payload())
    audit = AuditReceipt.model_validate(audit_payload())
    assert request.transfer_mode == "none"
    assert request.submission_enabled is False
    assert audit.contains_raw_context_values is False

    submitted = consent_request_payload()
    submitted["transferMode"] = "post"
    submitted["submissionEnabled"] = True
    with pytest.raises(ValidationError):
        ConsentRequest.model_validate(submitted)
    raw = audit_payload()
    raw["containsRawContextValues"] = True
    with pytest.raises(ValidationError):
        AuditReceipt.model_validate(raw)
