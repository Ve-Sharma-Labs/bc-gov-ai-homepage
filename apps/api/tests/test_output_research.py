import pytest
from ag_ui.core import (
    CustomEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from pydantic import ValidationError

from bc_api.errors import ApiError
from bc_api.output import OutputGate
from bc_api.research import PublicResearchTopic, WebIqPolicy
from bc_api.retrieval import EvidenceLedger
from bc_api.urls import official_url, validate_public_destination


def make_gate(repository, evidence, text):
    ledger = EvidenceLedger()
    ledger.add(evidence)
    gate = OutputGate(repository, ledger)
    gate.hold(TextMessageStartEvent(message_id="answer", role="assistant"))
    gate.hold(TextMessageContentEvent(message_id="answer", delta=text))
    gate.hold(TextMessageEndEvent(message_id="answer"))
    return gate


def test_late_native_annotations_are_preserved_and_enriched(repository, evidence):
    gate = make_gate(repository, evidence, "Bring accepted identification to the office.")
    gate.hold(
        CustomEvent(
            name="annotations",
            value={
                "messageId": "answer",
                "annotations": [
                    {
                        "type": "citation",
                        "url": evidence.evidence[0].reference.url,
                        "title": "Original",
                        "annotated_regions": [
                            {"type": "text_span", "start_index": 0, "end_index": 20}
                        ],
                    }
                ],
            },
        )
    )
    result = gate.finish()
    annotation = result[-1].value["annotations"][0]
    assert annotation["sourceId"] == "test-source"
    assert annotation["documentVersion"] == "test-version"
    assert annotation["publisherUpdatedAt"] is None
    assert annotation["annotated_regions"][0]["end_index"] == 20
    assert result[-2].type == "TEXT_MESSAGE_END"


def test_markdown_citations_get_source_metadata(repository, evidence):
    url = evidence.evidence[0].reference.url
    result = make_gate(
        repository, evidence, f"Prepare your documents. [Official guidance]({url})"
    ).finish()
    assert result[-1].name == "annotations"
    assert result[-1].value["annotations"][0]["sourceId"] == "test-source"


@pytest.mark.parametrize(
    "text,code",
    [
        ("An invented answer without sources.", "CITATION_REQUIRED"),
        ("<script>alert(1)</script>", "OUTPUT_INVALID"),
        ("![Image](https://example.com/a)", "OUTPUT_INVALID"),
        ("I have renewed your licence.", "TRANSACTION_CLAIM_BLOCKED"),
        ("Your application has been submitted.", "TRANSACTION_CLAIM_BLOCKED"),
        ("You are eligible for this program.", "TRANSACTION_CLAIM_BLOCKED"),
        ("See [guide](javascript:alert)", "CITATION_INVALID"),
        ("See https://www2.gov.bc.ca/gov/content/never-retrieved", "CITATION_INVALID"),
    ],
)
def test_unsafe_or_ungrounded_output_is_withheld(repository, evidence, text, code):
    gate = make_gate(repository, evidence, text)
    with pytest.raises(ApiError) as error:
        gate.finish()
    assert error.value.code == code


def test_invented_citation_and_high_risk_facts_are_blocked(repository, evidence):
    url = evidence.evidence[0].reference.url
    gate = make_gate(repository, evidence, f"The fee is $12345. [Source]({url})")
    with pytest.raises(ApiError) as error:
        gate.finish()
    assert error.value.code == "CRITICAL_CLAIM_UNVERIFIED"
    gate = make_gate(repository, evidence, "A claim.")
    gate.hold(
        CustomEvent(
            name="annotations",
            value={
                "messageId": "answer",
                "annotations": [{"url": "https://www.icbc.com/invented"}],
            },
        )
    )
    with pytest.raises(ApiError) as error:
        gate.finish()
    assert error.value.code == "CITATION_INVALID"


def test_exact_critical_evidence_quotation_is_required(repository, evidence):
    url = evidence.evidence[0].reference.url
    assert make_gate(repository, evidence, f"The fee is $75. [Source]({url})").finish()


def test_neutral_attribution_keeps_an_exact_qualified_quote_bound_to_its_source(
    repository, evidence
):
    item = evidence.evidence[0]
    item.reference.title = "Synthetic fee regulation"
    item.content = "For a driver's licence issued for more than 4 years: $75."
    text = (
        "If you're also checking cost, the regulation says: "
        "\u201cFor a driver\u2019s licence issued for more than 4 years: $75.\u201d "
        f"[Source]({item.reference.url})"
    )
    assert make_gate(repository, evidence, text).finish()


@pytest.mark.parametrize(
    "prefix,claim",
    [
        ("The regulation says:", "For a driver's licence issued for more than 4 years: $76."),
        ("The regulation says:", "For a driver's licence: $75."),
        (
            "For you, the regulation says:",
            "For a driver's licence issued for more than 4 years: $75.",
        ),
        (
            "For another programme, the source says:",
            "For a driver's licence issued for more than 4 years: $75.",
        ),
    ],
)
def test_attribution_cannot_change_a_price_qualifier_or_personal_scope(
    repository, evidence, prefix, claim
):
    item = evidence.evidence[0]
    item.reference.title = "Synthetic fee regulation"
    item.content = "For a driver's licence issued for more than 4 years: $75."
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(
            repository, evidence, f'{prefix} "{claim}" [Source]({item.reference.url})'
        ).finish()


def test_neutral_quote_cannot_use_a_different_cited_document(repository, evidence):
    item = evidence.evidence[0]
    item.content = "The fee is $75."
    other = item.model_copy(deep=True)
    other.reference.document_id = "other-document"
    other.reference.url = item.reference.url + "/other"
    other.content = "A different synthetic source without fee information."
    evidence.evidence.append(other)
    text = (
        f"Background [Source]({item.reference.url}).\n\n"
        f'The source says: "The fee is $75." [Other source]({other.reference.url})'
    )
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, text).finish()


@pytest.mark.parametrize(
    "programme", ["guardianship-adult", "guardianship-child", "disability-assistance"]
)
def test_incremental_probes_preserve_the_programme_navigation_scope(
    repository, evidence, programme
):
    from bc_api.conversation_grounding import PROGRAMMES

    url = evidence.evidence[0].reference.url
    handoff = PROGRAMMES[programme].handoff
    text = (
        f"Synthetic preparation guidance. [Source]({url})\n\nNext: [Official guidance]({handoff})"
    )
    gate = make_gate(repository, evidence, text)
    gate.programme_id = programme
    assert gate.flush_sections()
    assert gate.finish()
    denied = make_gate(repository, evidence, text)
    denied.programme_id = "ei-regular"
    with pytest.raises(ApiError, match="CITATION_INVALID"):
        denied.flush_sections()


@pytest.mark.parametrize("prefix,suffix", [("", ""), ('"', '"'), ("> ", ""), ('> "', '"')])
def test_quote_presentation_does_not_change_verified_words(repository, evidence, prefix, suffix):
    item = evidence.evidence[0]
    item.content = "The fee is $75 , including dispensing services."
    text = f"{prefix}The fee is $75, including dispensing services.{suffix}"
    assert make_gate(repository, evidence, f"{text} [Source]({item.reference.url})").finish()


@pytest.mark.parametrize(
    "source,claim",
    [
        ("The fee is $750.", "The fee is $75."),
        ("The fee is $75.50.", "The fee is $75."),
        ("The fee is $75 for adults only.", "The fee is $75."),
        ("The fee is $75, not $50.", "The fee is $75."),
        ("The fee is -$75.", "The fee is $75."),
    ],
)
def test_critical_quotes_cannot_drop_digits_signs_or_qualifications(
    repository, evidence, source, claim
):
    item = evidence.evidence[0]
    item.content = source
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, f"{claim} [Source]({item.reference.url})").finish()


def test_inline_link_text_cannot_hide_a_changed_critical_claim(repository, evidence):
    url = evidence.evidence[0].reference.url
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, f"The fee is [not]({url}) $75. [Source]({url})").finish()


def test_cited_programme_description_is_not_a_specific_fee_claim(repository, evidence):
    item = evidence.evidence[0]
    item.content = "PharmaCare helps with eligible prescriptions, dispensing fees and supplies."
    answer = (
        "PharmaCare supports eligible prescription medicines and dispensing fees. "
        f"[Source]({item.reference.url})"
    )
    assert make_gate(repository, evidence, answer).finish()


def test_fee_navigation_is_not_an_assertion_of_an_amount_or_obligation(repository, evidence):
    url = evidence.evidence[0].reference.url
    assert make_gate(
        repository,
        evidence,
        "If you want the exact fee that applies to your renewal, check the official schedule. "
        f"[Source]({url})",
    ).finish()
    assert make_gate(
        repository, evidence, f"Pay attention to the published guidance. [Source]({url})"
    ).finish()


@pytest.mark.parametrize(
    "question",
    [
        "Which notice must be served?",
        "Ask your legal adviser what deadlines apply.",
        "Which fees are payable?",
    ],
)
def test_suggested_questions_do_not_assert_a_price_or_legal_requirement(
    repository, evidence, question
):
    url = evidence.evidence[0].reference.url
    assert make_gate(repository, evidence, f"{question} [Source]({url})").finish()


@pytest.mark.parametrize(
    "claim",
    [
        "The notice must be served.",
        "What is the $76 fee?",
        "Ask why there is no fee.",
        "What deadline is next Monday?",
        "Which report must be filed within ten days?",
    ],
)
def test_questions_cannot_hide_specific_or_waived_obligations(repository, evidence, claim):
    url = evidence.evidence[0].reference.url
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, f"{claim} [Source]({url})").finish()


@pytest.mark.parametrize(
    "claim",
    [
        "A fee applies.",
        "The fee that applies is mandatory.",
        "The fee which applies is $20.",
        "Required fees apply to this renewal.",
        "Pay the fee that applies to your renewal.",
    ],
)
def test_relative_fee_references_cannot_hide_actual_payment_claims(repository, evidence, claim):
    url = evidence.evidence[0].reference.url
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, f"{claim} [Source]({url})").finish()


@pytest.mark.parametrize("text", ["Feel free to check the guidance.", "Ask a free-form question."])
def test_nonfinancial_free_idioms_are_not_fee_assertions(repository, evidence, text):
    url = evidence.evidence[0].reference.url
    assert make_gate(repository, evidence, f"{text} [Source]({url})").finish()


@pytest.mark.parametrize(
    "claim",
    [
        "The service is free.",
        "There are no fees.",
        "You pay dispensing fees.",
        "The fees are covered.",
        "Registration fees apply.",
        "The fees don't apply.",
        "This has a fee.",
        "The programme charges registration fees.",
        "There are reduced fees.",
        "Fees: waived.",
        "The programme pays 70% of eligible costs.",
    ],
)
def test_unquantified_payment_terms_and_rates_still_need_exact_quotes(repository, evidence, claim):
    url = evidence.evidence[0].reference.url
    with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
        make_gate(repository, evidence, f"{claim} [Source]({url})").finish()


@pytest.mark.parametrize(
    "url",
    [
        "http://www2.gov.bc.ca/",
        "https://www2.gov.bc.ca.evil.example/",
        "https://www2.gov.bc.ca@evil.example/",
        "https://user:password@www2.gov.bc.ca/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://www2.gov.bc.ca:8443/",
        "https://www2.gov.bc.ca\\@evil.example/",
        "https://www2.gov.bc.ca/%0d%0a",
    ],
)
def test_official_url_restrictions(url):
    with pytest.raises(ValueError):
        official_url(url)


async def test_research_has_no_free_text_or_network_and_stays_disabled(settings, monkeypatch):
    calls = []

    def denied(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("No research network operation is permitted.")

    monkeypatch.setattr("socket.getaddrinfo", denied)
    policy = WebIqPolicy(
        settings.model_copy(
            update={
                "webiq_enabled": True,
                "webiq_app_id": "test-app",
                "webiq_privacy_approval_id": "test-review",
                "webiq_terms_approval_id": "test-review",
                "webiq_egress_approved": True,
                "webiq_zero_query_logging_approved": True,
                "webiq_transient_handling_verified": True,
            }
        )
    )
    assert not policy.enabled and policy.unmet_gates == (
        "release_review", "source_review", "approved_paths",
    )
    topic = PublicResearchTopic(topic="service-bc", geography="vancouver")
    assert "Vancouver" in topic.query()
    with pytest.raises(ApiError) as error:
        await policy.research(topic)
    assert error.value.code == "WEBIQ_DISABLED"
    assert calls == []
    for payload in [
        {"topic": "PHN 12345678"},
        {"topic": "health-coverage", "query": "my health history"},
        {"topic": "service-bc", "geography": "123 Home Street"},
    ]:
        with pytest.raises(ValidationError):
            PublicResearchTopic.model_validate(payload)


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fd00::1"],
        ["93.184.216.34", "10.1.2.3"],
        [],
    ],
)
async def test_private_dns_is_rejected(addresses):
    async def resolver(host):
        return addresses

    with pytest.raises(ValueError):
        await validate_public_destination(
            "https://www2.gov.bc.ca/gov/content/health", resolver=resolver
        )


async def test_redirects_revalidate_every_host_and_bound_hops():
    async def resolver(host):
        return ["93.184.216.34"]

    url = "https://www2.gov.bc.ca/gov/content/health"
    assert await validate_public_destination(url, resolver=resolver) == url
    with pytest.raises(ValueError):
        await validate_public_destination(
            url, redirect_chain=("https://evil.example/",), resolver=resolver
        )
    with pytest.raises(ValueError):
        await validate_public_destination(url, redirect_chain=(url,) * 4, resolver=resolver)
