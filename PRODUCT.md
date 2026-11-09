# BC Government service assistant

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People seeking information about British Columbia government services and help
understanding the next steps. Specific research cohorts and supported languages
remain open decisions.

## Product Purpose

Create a polished, conversational front door to BC government information and
services, inspired by the simplicity and interaction quality of America.gov.
Help people find authoritative answers through general B.C. conversation, with
guided service journeys available when useful rather than required before chat.

## Operating Context

The first release is an anonymous public preview with real BC-source answers,
preparation plans and official handoffs. Live public research is a separately
approved opt-in, not a dependency: the core must work with its approved corpus
and official handoffs if Web IQ approval is unavailable.

Later releases may complete approved transactions through agency integrations.
Driver's licence renewal is a requested example of a future agent-led journey;
the pilot must not claim to renew a licence or submit an application.

A separate, repository-implemented but unreleased
[citizen-context ADM validation demo](docs/citizen-context-demo.md) preserves
anonymous mode as the default while adding three fixed synthetic personas for
guardianship/caregiving, disability support, and job loss. It uses deterministic
screening rules, consented fictional facts, reviewable previews, and official
handoffs. It does not use a real BC Services Card account, access government
records, decide eligibility, or submit anything. The specification defines a
future production identity and Context Broker contract. The
[ADM demonstration package](docs/citizen-context-adm-demo.md) and
[executive brief](docs/citizen-context-executive-brief.md) support a decision
session; neither claims deployment or authorizes activation.

## Capabilities and Constraints

- Azure and Microsoft Foundry are required for the AI and application backend.
- Retain the implemented Next.js/React, Python API, Agent Framework and AG-UI.
- Both light and dark modes are required.
- Microsoft Web IQ is a requested live-information capability. The user approved
  planning it only for non-personal public-information queries, subject to
  privacy review; the application core remains on Azure.
- One general and five pathway managed/versioned Foundry prompt agents share API-owned functions.
  No custom Hosted Agent containers are required.
- Main chat does not wait for capability discovery or require a pathway. Social
  dialogue, sourced model answers and official handoffs are clearly distinguished.
  Facts require reviewed evidence; source-free dialogue is not a bypass for facts.
- Direct Azure AI Search remains the fast default. Two disabled-by-default,
  per-answer actions can add a separate supplement: Foundry IQ preview planning
  over the same approved corpus, or Web IQ research on separately approved public
  pages. Neither runs automatically, changes the original answer, imports personal
  context, or expands source permissions. Each needs its own release approval.
  Work IQ and Fabric IQ remain outside the anonymous pilot.
- Global Azure model processing is accepted for this pilot, not as blanket
  approval of Web IQ terms or future production processing.
- Ground answers in the supplied provincial, agency, and Crown corporation sites.
- Cover ministry guidance, Service BC, housing, health, family supports,
  employment, taxes, BC Housing, ICBC, WorkBC, HealthLink BC, and BC Laws.
- Content discovery and specification work do not authorize account access,
  credential collection, payment, or submission of a resident's transaction.

## Brand Commitments

The product is intended for BC Government. America.gov is a reference for
experience quality, not a source of branding, photographs, or copied code.
The limited pilot uses the user-approved BC assets and release labelling.
This does not imply a broader government-brand or production certification.

The user rejected the first pilot's visual design as too far from America.gov.
The homepage and How it works page are now explicit references for composition,
typography hierarchy, imagery, component geometry and motion, not merely
inspiration for a generic government portal. The next UI pass follows
[the reference-fidelity rebuild specification](docs/ui-fidelity-rebuild.md).
The user selected a display serif for the headline treatment, with BC Sans
retained for body/UI text. The selected fonts are openly licensed; the limited public pilot uses the
subsequently approved BC brand treatment.

The replacement local UI uses open-licensed Libre Caslon Display and BC Sans,
with provenance-checked photographs of BC selected per the user's instruction.
It implements shadcn/Base UI, Motion and an adapted Magic UI entrance component.

## Evidence on Hand

The user supplied twelve starting URLs and their intended content coverage.
The repository initially contained only its name in README.md. It now contains
the local web/API implementation, a dated twelve-source catalogue, controlled
ingestion tooling, a documented visual design, and a deployed Azure pilot.
The general-chat release is live with one general and five pathway agents.
The index still contains only four explicitly approved documents; a twelve-source
registry is not full-text coverage. Broader acquisition and publication remain gated.
The redesigned UI includes dedicated How it works and expanded chat pages,
immediate submission/error navigation and progressively validated answer sections.
It retains drafts, conversations and checklist progress in tab memory during
internal navigation; reload and Start over clear them. Theme is the only locally
persisted preference.

## Product Principles

- Start with the person's task rather than the government organisation chart.
- Distinguish sourced guidance, live research, and actions the service can
  actually complete.
- Make next steps and authoritative evidence visible.
- Keep pilot handoffs honest; expand authority only with approved integrations.

## Context-first conversation increment

The AI-led version-5 increment supersedes keyword-first discovery when
explicitly enabled. One isolated Foundry conversation agent interprets the
current request, including typos and short follow-ups, and proposes a typed
next step. The API owns the final question, permissions, essential-field
checks, and choice of reviewed guide. An unclear request receives clarification,
not a false unsupported-service answer. A known guide can be offered even when
Search lacks enough evidence for detailed factual generation.

The subsequent task-assistance increment keeps a current catalogue step,
user-reported readiness, and the next useful action. The conversation actively
walks through preparation across the seven existing journeys. A repeated help
request or frustrated check-in must not restart intake or simply repost a guide.
The guide remains available; practical step guidance leads. Sharing changes
are settings, not messages attributed to the person. Step progress is never
evidence that an official service was completed.

The default chat is messages and one composer, not an intake form. Full guides,
checklists, context, and sharing controls live in optional Details. Starter
questions for renewal, guardianship, disability support, and job loss fill the
composer for review; they do not send, overwrite a draft silently, or activate
a fictional persona.

An answer offered by the application must always be accepted by its own
question contract. Canonical labels and unambiguous short replies are resolved
before any model interpretation, tied to the pending question and revision.
Already-known answers are not re-asked. For a non-B.C. licence, clarify renewing
with the original issuer versus getting a B.C. licence; do not apply the B.C.
renewal checklist to both. Uncertainty remains explicit.

Guardianship and disability entry questions select public information topics,
not personal records, legal capacity, diagnoses, or eligibility. Their
navigation links are not full application journeys or new Search publications.
Outside reviewed coverage, name the specific limitation and the appropriate
authority instead of inventing a procedure.

Version 5 explicitly discloses Azure message processing and offers optional
personal-context sharing, off by default. Only relevant self-reports the person
chooses to share can inform later model requests; identifiers and sensitive
documents remain prohibited. Removal stops future use, not past processing.
Version-4 context is never silently imported. The existing BC visual identity
and read-only/official-handoff boundaries are unchanged. An isolated local
agent is not an approval to update the public pilot.

The following describes the retained version-4 compatibility mode:

The repository now includes a separately gated, goal-first discovery flow.
It is not a claim that the public pilot has been updated. Begin with the
person's goal, acknowledge the situation warmly, and ask at most three
relevant questions one at a time before a useful first plan or official handoff.
Facts already volunteered are not requested again. Every question can be
skipped; simple factual questions do not require a profile.

Persona labels stay behind the scenes. An editable **What I understand**
summary makes the current goal, self-reported context, uncertainty, and
suggested pathways visible. Context is page-bound and expiring, not a durable
citizen profile. Age and PHN possession are only navigation context; the actual
PHN, credentials, documents, and medical histories remain prohibited.
Immigration-status collection remains gated on a specific reviewed program.

Maya, Alex, and Sam are still fictional fixtures. A conversation may recommend
an optional scenario, but explicit selection and purpose-specific consent are
required before any fixture facts are used. Signing in to BCeID or BC Services
Card is not a substitute for authorized program-data access; neither real
sign-in nor record integration is part of this increment.

`CONVERSATION_DISCOVERY_ENABLED` is false by default. Production also requires
the privacy-review flag; the code does not authorize public activation, new
source publication, or transactions.

## Grounded continuation candidate

The next increment separates the question being answered from preparation
progress and introduces programme-aware continuity, including EI under job
loss. It targets useful sourced answers across the four starter flows,
not another static checklist or persona workflow. Current compatibility
repairs must acknowledge source gaps rather than loop.

The version-6 implementation remains opt-in and its source packs are
candidate metadata only. Full grounding is not ready until the four-flow
coverage, publisher rights, exact source review, prompt evaluation and local
acceptance gates pass. Existing reviewed sources are not blanket permission
to acquire new B.C., ICBC, PGT, or Canada.ca material. Public deployment and
real transactions remain out of scope.

## Accepted Planning Baseline

On October 24, 2026, the user adopted the
[pilot specification](docs/pilot-specification.md) as the planning baseline.
They subsequently authorized implementation in fleet mode and selected local
execution with Azure configuration preparation, without provisioning resources.

The baseline uses Next.js/React and BC components, AG-UI, Microsoft Agent
Framework with Foundry Agent Service, Azure AI Search, and Azure Container Apps.
The native SDK/AG-UI combination has offline contract coverage and has subsequently
been exercised with real Azure identity, source grounding, ingress and cancellation.

Subsequent approval covered the isolated Azure/public pilot and the general-chat
increment. The deployed service uses shared anonymous controls and managed
identity. The approved four-snapshot publication does not authorize new hashes
or every page on the requested sites.

The five initial journeys are licence-renewal preparation, rental assistance,
MSP/PharmaCare, primary-care navigation, and Service BC locations. Later areas and
gated sources remain visible in the source registry rather than being presented
as completed coverage.

## Open Decisions

The target is all permitted public pages across the twelve requested areas,
using Direct Search first. Remaining decisions concern actual source rights and
new snapshot approvals, unsupported feed/document formats, future citizen identity,
language rollout and production certification. The established pilot target,
model, public access and billing authorization are not unresolved decisions.
Restricted crawling, Web IQ activation and resident transactions remain unapproved.
The synthetic citizen-context demo is implemented behind a disabled-by-default
source flag and enabled in the reviewed public pilot environment. Any use of real citizen
context remains separately gated by identity, privacy, security, data-steward,
consent, and program-owner approval.
