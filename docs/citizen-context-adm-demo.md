# Citizen-context ADM demonstration and decision package

**Status:** Facilitation package for the deployed synthetic public-pilot demo.
The capability remains disabled by default in source configuration and is not
connected to any real citizen identity or government record.

**Prepared:** October 29, 2026

**Recommended primary path:** Maya's adult-guardianship information flow. It
provides the cleanest anonymous-versus-context comparison, two deterministic
navigation matches, six populated preview fields, and one deliberately missing
qualified-review item. Use Alex and Sam as shorter alternate paths.

**Decision sought:** Whether the value hypothesis merits a governed pilot and,
if so, which sponsor, data categories, human-review boundary, and first
read-only source integration should proceed to formal discovery.

## 1. Opening script

Use this wording before touching the interface:

> This is a synthetic demonstration. Maya, Alex, and Sam are fictional. No BC
> Services Card account, real government record, application, or case system is
> connected. Program results are deterministic screening indicators, not
> eligibility decisions. The preview is not submitted or transferred. We are
> evaluating whether consented context could reduce repeated questions while
> preserving review, consent, evidence, and human-accountability boundaries.

Allow 12-15 minutes for the primary path, 3-4 minutes for each alternate, and
15 minutes for decisions.

## 2. Primary live storyboard: Maya

Run this path only after the [operator preflight](#10-demo-operator-checklist)
is green. The live wording may vary because the explanatory response is model
generated; the server-owned artifacts and boundaries must not vary.

| Time | Operator action | Facilitator narration and decision cue |
|---|---|---|
| 0:00 | Open a fresh page. Point to `Context: Anonymous`. | "Anonymous is the default. No citizen context is available." |
| 0:30 | Ask: **I need to apply for guardianship.** | "The anonymous service can provide sourced general navigation, or an honest source-unavailable handoff, but it has no persona facts, screening artifacts, or preview." Do not promise exact model wording. |
| 1:30 | Note the absence of the synthetic banner, context drawer, program-screening artifact, and preview. | "The independent evaluator identifies one intent clarification plus four deterministic fact gaps in the anonymous comparison. That is a model-free comparison, not a claim that the live model will ask exactly five questions." |
| 2:00 | Select **Start over** and confirm. | "We will now ask the identical question with a fictional, consented context." |
| 2:30 | Open the context selector and choose **Maya synthetic**. | Read the synthetic notice aloud. Required categories are Household and dependants, Disability or caregiving circumstances, and Existing programs and applications. Region and service preferences is suggested but optional. |
| 3:30 | Leave the proposed categories selected and choose **Use selected context**. | "Consent is purpose-specific and category-based. The browser sends the persona ID and selected scopes, not fixture facts." |
| 4:00 | Point to the **Synthetic citizen context** banner. Open **What the assistant used**. | Show purpose, categories, provenance, freshness, and the ability to remove optional consent or return to anonymous. |
| 5:00 | Ask again: **I need to apply for guardianship.** | "The same request now runs through the dedicated contextual mode. Facts, rules, previews, and artifacts remain server-owned." |
| 6:00 | Show **Program screening**. | Two expected indicators are `Family social supports navigation` and `Service B.C. assisted navigation`, both labelled **Potential match**. Read the screening notice: this is not eligibility, legal advice, or a capacity decision. |
| 7:00 | Show **Still needed** and the preview's **Professional capacity information** field. | "One item remains deliberately missing. A qualified reviewer must decide whether professional capacity information is relevant. This build does not convert chat text into an authoritative or citizen-answer preview field, so we leave it missing." |
| 8:00 | Show **Application or intake preview**. | Six fields are populated from synthetic records; one is missing. Point to field-level provenance, confirmation requirements, `Review only`, and the absence of a Submit action. |
| 9:00 | Show **Consent checkpoint**. Select the review checkbox. | Read `Transfer in this demo: None`. "Continue to official service" opens an official page only; it sends no preview values, identifiers, or context. |
| 10:00 | Show **Audit receipt**. | "The receipt records category access, rule/source versions, preview creation, handoff, and run completion. It contains no raw context or preview values." |
| 11:00 | Open **What the assistant used** and choose **Return to anonymous**. | Verify the banner, context chip, contextual conversation, and artifacts disappear and the selector reads `Anonymous`. "Revocation and reset remove contextual access; anonymous guidance remains available." |

### What to avoid saying

- Do not say Maya was authenticated, found, or matched to a real record.
- Do not say the parent lacks capacity or that guardianship is necessary.
- Do not call a potential match "eligible", "approved", or "recommended by AI".
- Do not say the preview was saved, submitted, transferred, or received.
- Do not describe the current public deployment as supporting this flow.

## 3. Short alternate paths

### Alex: disability-support navigation

Use the same anonymous/contextual comparison with:

> I need to apply for disability.

Key points:

- The intent clarification remains appropriate: the service must still ask
  which kind of disability support Alex means. Context does not replace intent.
- Required categories are identity/residency, employment/income,
  disability/caregiving, and existing programs. Region/preferences is optional.
- The deterministic package uses 10 synthetic facts and produces two potential
  navigation matches.
- Six preview fields are populated. The single missing item is the **Qualified
  practitioner section**, which the assistant cannot complete.
- The assistant does not diagnose, assess severity or functional capacity,
  complete medical evidence, calculate a benefit, or decide eligibility.

### Sam: job-loss navigation

Use:

> I just lost my job. What do I do?

Key points:

- All five proposed categories are required by the fixed Sam flow.
- The deterministic package uses 11 synthetic facts and shows three potential
  navigation matches: employment/business, provincial income assistance, and
  housing/tenancy.
- Nine preview fields are populated. Four items remain for official
  confirmation: immediate housing risk, separation reason, insurable-hours
  category, and Employment Insurance application status.
- Employment Insurance approval is not predicted. No EI or WorkBC eligibility
  match is fabricated where reviewed program-specific evidence is absent.
- This path best demonstrates breadth, but it is longer and has more missing
  items than the recommended Maya path.

## 4. What this proves and what it does not prove

### What the demonstration proves

- Anonymous mode remains the default and contextual mode is explicit.
- Only three fixed fictional personas can be selected.
- Category-level consent precedes access to synthetic facts.
- Context, rule results, preview fields, source versions, and artifacts use
  strict server-owned contracts.
- The same versioned inputs produce deterministic screening results.
- The interface distinguishes potential matches, missing information,
  provenance, human review, and official handoff.
- The checkpoint has `transferMode: "none"` and the preview has
  `submissionEnabled: false`.
- A value-free audit receipt can explain what was accessed and evaluated.
- Revocation, reload binding loss, and reset remove contextual access.
- Automated evaluation can quantify deterministic question reduction and
  artifact completeness without calling a remote model.

### What the demonstration does not prove

- It does not prove production deployment, live contextual-agent readiness, or
  complete Search coverage.
- It does not prove generated-answer quality, policy correctness, real-world
  adoption, or formal program eligibility accuracy.
- Synthetic records do not prove that real records are complete, current,
  consistent, linkable, or available through APIs.
- It does not authenticate a citizen or integrate BC Services Card, BC
  Government SSO, a Context Broker, Microsoft Entra Agent ID, or a program
  system.
- It does not provide legal or medical judgment, determine capacity, diagnose,
  calculate benefits, or replace a qualified reviewer.
- It does not currently turn a conversational answer into a persisted
  `citizen-answer` preview field.
- It does not submit, sign, pay, book, upload, create a case, or return an
  authoritative confirmation number.
- It does not authorize a real-data pilot or public activation.

## 5. Questions for the ADM

Record a decision owner and due date for each question.

| Decision area | Questions |
|---|---|
| Value hypothesis | Is avoiding repeated questions and producing a reviewable next-step package valuable enough to justify identity, consent, source-integration, and governance cost? Which of the three flows best represents that value? What outcome would cause us to stop? |
| Acceptable data categories | Which categories could be considered for a real pilot: identity/residency, household/dependants, employment/income, disability/caregiving, existing programs, or region/preferences? Which are prohibited or require a higher assurance level? |
| Human-review boundaries | Which outputs must always remain informational? Which facts, rules, previews, or actions require a program officer, legal professional, qualified practitioner, or other accountable human? Who owns corrections and appeals? |
| Pilot sponsor | Which ADM, ministry program, product owner, privacy lead, security lead, data steward, records owner, accessibility lead, and operations owner will sponsor and stop the pilot if a gate fails? |
| First real system integration | If discovery proceeds, what is the narrowest read-only source adapter with clear authority, stewardship, freshness, correction, and support? Is there a lower-risk flow than guardianship or disability with which to start? |
| Governance appetite | Is the organization prepared to fund a PIA, STRA, identity onboarding, data-sharing authority, source-specific stewardship, retention design, rule ownership, independent evaluation, incident response, and kill-switch operations before real data is used? |

The requested decision is not "approve production." It is one of:

1. Stop after the synthetic demonstration.
2. Continue synthetic research only.
3. Authorize governed discovery for one read-only, non-transactional
   integration, subject to all external approvals.

## 6. Success measures

### Demonstration measures

| Measure | Maya | Alex | Sam | Interpretation |
|---|---:|---:|---:|---|
| Anonymous entry + deterministic fact questions | 1 + 4 | 1 + 6 | 0 + 7 | Model-free comparison baseline |
| Contextual entry + deterministic fact questions | 0 + 0 | 1 + 0 | 0 + 0 | Intent clarification is preserved where still necessary |
| Synthetic facts used | 7 | 10 | 11 | Only consented, allowlisted facts used by a rule or preview |
| Program-screening artifacts | 2 | 2 | 3 | All current fixture results are `potential-match` |
| Populated preview fields | 6 | 6 | 9 | Review aids, not submitted forms |
| Missing preview items | 1 | 1 | 4 | Unknowns remain visible rather than inferred |
| Artifact order complete | 5 of 5 | 5 of 5 | 5 of 5 | Summary, matches, preview, checkpoint, audit |

These are deterministic fixture measurements. They are not model-quality or
real-program accuracy scores.

### ADM-session success

The session succeeds if the ADM can accurately state:

- the user value being tested;
- that all people and records are synthetic;
- the difference between screening and eligibility;
- which missing item remains for human or official review;
- that the checkpoint transfers nothing and there is no submission path;
- what approvals would be required before real data; and
- whether to stop, continue synthetic research, or sponsor governed discovery.

## 7. Evidence map

Results below were reproduced locally on October 29, 2026. They do not prove a
deployed contextual release.

| Claim | Automated evidence | Reproducible result |
|---|---|---|
| Three anonymous/contextual comparisons and exact measures | [Evaluation manifest](../data/citizen-context-evaluation-cases.json), [read-only evaluator](../scripts/evaluate-context-demo.py), [evaluation test](../apps/api/tests/test_context_evaluation.py) | `npm run evaluate:context`: passed; three cases; zero failures; `remoteModelCalls: 0` |
| Fixed personas, fixture provenance, and scope contracts | [Persona fixture](../data/demo-personas.json), [persona tests](../apps/api/tests/test_demo_personas.py), [API context tests](../apps/api/tests/test_context_api.py) | Included in 121 passing targeted API tests |
| Deterministic rules, source versions, and flow boundaries | [Rule fixture](../data/demo-program-rules.json), [rule tests](../apps/api/tests/test_demo_rules.py), [Maya](../apps/api/tests/test_guardianship_flow.py), [Alex](../apps/api/tests/test_context_flow_disability.py), [Sam](../apps/api/tests/test_context_flow_job_loss.py) | Included in 121 passing targeted API tests |
| Consent, isolation, revocation, audit, no submission route, and overreach blocking | [Runtime tests](../apps/api/tests/test_context_agent_runtime.py), [audit tests](../apps/api/tests/test_context_audit.py), [contract tests](../apps/api/tests/test_context_contracts.py), [evaluation tests](../apps/api/tests/test_context_evaluation.py) | 121 targeted API tests passed |
| Typed rendering of consent, context, matches, preview, checkpoint, audit, and reset | [Web context tests](../apps/web/tests/citizen-context.test.tsx), [artifact tests](../apps/web/tests/chat-artifacts-context.test.tsx), [provider tests](../apps/web/tests/context-provider.test.tsx) | 21 targeted web tests passed |
| Anonymous/contextual browser comparison, keyboard behavior, no browser persistence, reload invalidation, light/dark and automated accessibility | [Browser context suite](../tests/browser/context.spec.mjs) | 10 tests passed across desktop and mobile; retain the Playwright report and generated light/dark screenshots as session evidence |
| No real identity claim | [Implementation contract](implementation-contract.md), [future identity contract](citizen-context-identity.md) | Capability literals remain `realIdentityIntegrated: false` and `realCitizenIdentityConfigured: false` |

## 8. Governance narrative

The current demo is deliberately synthetic:

- Fixtures are hand-authored fiction and declare `productionDataUsed: false`.
- Deterministic, versioned rules produce navigation screening indicators.
- The model can explain immutable results but cannot change a status or source
  version.
- No real record, citizen account, source-system credential, or unrestricted
  source response is available to the model or browser.
- No submission route or tool exists. The checkpoint opens an official service
  without transferring preview values.
- Audit events contain opaque references, scopes, rule/source versions, tools,
  and outcomes, not raw facts or preview values.

A future production contract would require three independent proofs:

1. BC Government SSO/BC Services Card proves the citizen to the application.
2. Microsoft Entra Agent ID proves the contextual agent actor.
3. A purpose- and scope-bound consent receipt proves the citizen's current
   permission.

A separate Context Broker would authorize the combined subject, actor, purpose,
scope, consent, and named source adapter. BC Services Card is not a government
data warehouse, Agent ID is not citizen consent, and direct Keycloak-to-Entra
on-behalf-of is not assumed.

Before any real context, the responsible organizations must approve the PIA,
information-sharing authority, STRA, privacy zone and claims, data-steward
attribute allowlist, source authorization, correction route, retention,
accessibility, rule ownership, human-review boundary, incident response, and
kill switches. Each source adapter needs its own approval; the synthetic demo
cannot satisfy those gates.

## 9. Failure and recovery script

The governing rule is:

> Stop rather than substitute. A failed provider, missing consent, or
> unavailable reviewed source never becomes permission to answer from model
> memory, broaden scope, use another persona, or present stale artifacts.

| Failure | What the operator says | Recovery |
|---|---|---|
| Foundry/contextual agent unavailable | "The reviewed contextual agent is not available, so I will not substitute another agent or simulate a live answer." | Return to anonymous. Show the deterministic evaluator and browser-test evidence only if clearly labelled as automated evidence, not a live run. Verify the pinned contextual binding and policy before retrying. |
| Search unavailable or index empty | "Approved source retrieval is unavailable. The service will not generate a factual contextual explanation without reviewed evidence." | Use an official source handoff. Do not present model prose as grounded. Retry only after Search readiness is verified. |
| Synthetic context/session unavailable, expired, or changed | "The synthetic grant is no longer valid. No context will be used." | Choose **Return to anonymous**, reload, select the persona again, and re-grant the minimum categories. If the fixture or service remains unavailable, stop the contextual path. |
| Consent declined, missing, or insufficient | "Declining is a supported outcome. We will continue anonymously." | Do not auto-select or broaden categories. Reopen the consent sheet only if the participant asks; required categories cannot be removed while that fixed flow is active. |
| Reviewed rule/source version or retrieved evidence unavailable | "This is a source or policy availability failure, not missing citizen information. No screening result will be guessed." | Stop the contextual result, use the reviewed official destination, and require source/rule review before rerunning. |
| Audit receipt unavailable | "The run cannot demonstrate the required traceability boundary." | Do not call the run complete. Reset and retry after the audit dependency is healthy. |

## 10. Demo operator checklist

### Before the session

- [ ] Use an isolated, approved local or test environment. Do not use real
      citizen identities, records, credentials, or copied production data.
- [ ] Confirm `SYNTHETIC_CONTEXT_ENABLED` is explicitly enabled only for the
      demo environment; it remains `false` by default.
- [ ] Confirm a distinct pinned `FOUNDRY_CONTEXTUAL_AGENT` is configured and
      matches the reviewed policy and four-tool declaration.
- [ ] Confirm Search is ready and contains reviewed evidence whose source IDs
      and versions match the selected flow.
- [ ] Check `/api/capabilities`: request version 3 is supported,
      `syntheticContextAvailable` is true, and retrieval is ready. This is not
      sufficient by itself; complete one rehearsal run.
- [ ] Run `npm run evaluate:context` and retain the JSON output.
- [ ] Run the targeted API, web, and browser context suites in the intended
      build. Record failures; do not waive them verbally.
- [ ] Open a fresh browser tab and complete the primary path once.
- [ ] Prepare the official destination links and the failure script.
- [ ] Ensure no screen recorder, analytics tool, or browser extension will
      capture unintended content.

### During the session

- [ ] Read the synthetic/no-real-record opening statement.
- [ ] Start in anonymous mode and use the exact same question in both runs.
- [ ] Show category consent before showing facts.
- [ ] Say **potential match**, not eligible or approved.
- [ ] Show one missing item and leave it missing.
- [ ] Show `Transfer in this demo: None` and the absence of Submit.
- [ ] Show the value-free audit receipt.
- [ ] Do not type a real name, address, identifier, health detail, financial
      value, or case information into chat.

### Reset

1. Open **What the assistant used** and choose **Return to anonymous**.
2. Verify the synthetic banner, context chip, contextual messages, and five
   contextual artifacts are gone.
3. Verify the selector reads `Context: Anonymous`.
4. Choose **Start over** and confirm.
5. Reload the page. A prior page-bound grant must not reactivate.
6. Close the tab after the session. Server state is bounded and expires, but
   closing the tab is not a substitute for the visible reset.

If reset fails, stop using that tab and do not continue the demonstration until
the server-side session can be cleared.

## 11. Remaining release steps

These steps are not deployment authorization:

1. Record the ADM decisions in section 5 and name accountable owners.
2. Publish and verify the distinct contextual Foundry agent only through the
   existing reviewed publication controls.
3. Add reviewed Search evidence for every selected flow source and exact pinned
   version. The current deployed four-snapshot corpus does not cover all
   contextual flow sources.
4. Run live-provider end-to-end tests for all three flows; fixture-driven
   browser coverage is necessary but not sufficient for release.
5. Complete domain, legal/medical-boundary, privacy, security, accessibility,
   plain-language, source-owner, and operational review.
6. Capture a versioned evidence packet: build, agent version, rule hash, source
   versions, evaluator output, test report, screenshots, and reset proof.
7. Approve an environment-specific activation, monitoring plan, kill switch,
   rollback, and support script. Do not infer approval from repository code.
8. Treat any real citizen context as a separate program governed by the
   [production identity and data-access specification](citizen-context-identity.md).

## References

- [One-page executive brief](citizen-context-executive-brief.md)
- [Citizen-context normative specification](citizen-context-demo.md)
- [Production identity and data-access contract](citizen-context-identity.md)
- [Implementation contract](implementation-contract.md)
- [As-built deployed architecture](architecture.md)
