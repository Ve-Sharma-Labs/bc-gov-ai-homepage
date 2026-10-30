# Executive brief: consented citizen context

**Forwardable status:** Synthetic decision brief. The capability is deployed in
the reviewed public pilot, remains disabled by default in source configuration,
and is not connected to real citizen data.

## The opportunity

People often repeat the same facts while navigating government programs. The
synthetic citizen-context demonstration tests whether purpose-specific,
consented context could reduce that friction while keeping screening,
explanation, human review, consent, audit, and official handoff visibly
separate.

The recommended ADM demonstration uses **Maya**, a fictional resident caring
for an older parent:

1. Ask for guardianship help anonymously.
2. Select Maya and review category-level synthetic consent.
3. Ask the same question again.
4. Review two deterministic **potential** navigation matches.
5. Show six populated preview fields and one missing qualified-review item.
6. Show that the checkpoint transfers nothing and submits nothing.
7. Review the value-free audit receipt.
8. Return to anonymous mode and confirm the contextual material disappears.

## What exists

- Three fixed fictional personas: caregiving/guardianship, disability support,
  and job loss.
- Anonymous-by-default UX with category-level consent, provenance, freshness,
  revocation, and reset.
- Versioned deterministic screening rules and reviewed source-version checks.
- Server-owned context summary, program screening, review-only preview, consent
  checkpoint, and audit receipt.
- No submit, sign, pay, book, upload, or confirmation capability.
- Automated comparison evidence covering all three flows. The independent
  evaluator passes with no remote model calls.

The deterministic comparison shows:

| Flow | Anonymous question opportunities | Contextual question opportunities | Populated / missing preview items |
|---|---:|---:|---:|
| Maya | 5 | 0 | 6 / 1 |
| Alex | 7 | 1 | 6 / 1 |
| Sam | 7 | 0 | 9 / 4 |

These figures measure fixed fixture and rule behavior, not model-answer quality
or real eligibility accuracy.

## What does not exist

- No real BC Services Card or BC Government SSO sign-in.
- No real government record, source-system adapter, or citizen profile.
- No production Context Broker or Microsoft Entra Agent ID integration.
- No eligibility, legal-capacity, diagnosis, benefit, or approval decision.
- No application transfer or submission.
- No authorization to deploy the synthetic feature or begin a real-data pilot.

The current deployed Search corpus also does not cover every contextual flow
source, so repository implementation must not be described as a live release.

## Decision requested

The ADM is asked to choose one of three directions:

1. Stop after the synthetic demonstration.
2. Continue synthetic research only.
3. Sponsor governed discovery for one narrow, read-only, non-transactional
   source integration.

If discovery proceeds, decisions are required on:

- the value hypothesis and success threshold;
- acceptable and prohibited data categories;
- mandatory program, legal, medical, and citizen review boundaries;
- the accountable ADM, program owner, data steward, privacy/security leads, and
  operations owner;
- the first source system and minimum fact allowlist; and
- willingness to complete the PIA, information-sharing authority, STRA,
  identity onboarding, retention, correction, accessibility, rule governance,
  incident response, and kill-switch work.

## Recommended position

Approve an ADM demonstration and decision discussion, **not deployment**.
Use Maya as the primary path because it gives the clearest comparison and one
visible human-review gap. Use Alex to test medical/eligibility boundaries and
Sam to demonstrate multi-program breadth.

Any real context should start, if at all, with one low-risk read-only adapter,
one named purpose, a minimum fact allowlist, and no transaction authority. A
future design would require BC Services Card citizen proof, a distinct Agent ID
actor proof, a purpose-bound consent receipt, and a Context Broker that enforces
all of them together. Synthetic evidence cannot satisfy those production gates.

For the facilitator script, evidence map, recovery plan, and release steps, see
the [ADM demonstration package](citizen-context-adm-demo.md). Normative
boundaries are in the [citizen-context specification](citizen-context-demo.md)
and [production identity contract](citizen-context-identity.md).
