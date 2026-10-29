import { readFileSync } from "node:fs";

export const contextEvaluationCases = JSON.parse(readFileSync(
  new URL("../../../data/citizen-context-evaluation-cases.json", import.meta.url),
  "utf8",
)).comparisonCases;

const now = "2026-10-28T20:00:00Z";
const later = "2099-10-28T20:30:00Z";
const ruleVersion = "2026-10-28.1";

const definitions = {
  "maya-caregiver": {
    name: "Maya",
    flowId: "guardianship-intake",
    purpose: "personalize-guardianship-navigation",
    categories: [
      "household-dependants",
      "disability-caregiving",
      "existing-programs",
      "region-preferences",
    ],
    fact: {
      key: "household.relationship-to-care-recipient",
      label: "Relationship to person receiving care",
      category: "household-dependants",
      displayValue: "Adult child",
    },
    programs: [
      ["family-social-supports-navigation", "family-social-supports"],
      ["service-bc-assisted-navigation", "service-bc"],
    ],
    previewField: ["relationship", "Relationship to the person receiving care", "Adult child"],
    destinationName: "B.C. family and social supports",
    destinationUrl: "https://www2.gov.bc.ca/gov/content/family-social-supports",
  },
  "alex-disability-support": {
    name: "Alex",
    flowId: "disability-support",
    purpose: "personalize-disability-support",
    categories: [
      "identity-residency",
      "employment-income",
      "disability-caregiving",
      "existing-programs",
      "region-preferences",
    ],
    fact: {
      key: "employment.status",
      label: "Employment status",
      category: "employment-income",
      displayValue: "Part-time",
    },
    programs: [
      ["provincial-disability-support-navigation", "family-social-supports"],
      ["service-bc-assisted-navigation", "service-bc"],
    ],
    previewField: ["employment-status", "Employment status", "Part-time employment"],
    destinationName: "B.C. disability assistance information",
    destinationUrl: "https://www2.gov.bc.ca/gov/content/family-social-supports",
  },
  "sam-job-loss": {
    name: "Sam",
    flowId: "job-loss",
    purpose: "personalize-job-loss-navigation",
    categories: [
      "identity-residency",
      "household-dependants",
      "employment-income",
      "existing-programs",
      "region-preferences",
    ],
    fact: {
      key: "employment.status",
      label: "Employment status",
      category: "employment-income",
      displayValue: "Employment recently ended",
    },
    programs: [
      ["employment-business-navigation", "employment-business"],
      ["provincial-income-assistance-navigation", "family-social-supports"],
      ["housing-tenancy-navigation", "housing-tenancy"],
    ],
    previewField: [
      "employment-status",
      "Employment status",
      "Employment recently ended",
    ],
    destinationName: "B.C. employment and business services",
    destinationUrl: "https://www2.gov.bc.ca/gov/content/employment-business",
  },
};

function auditEvents(definition) {
  const [programId, sourceId] = definition.programs[0];
  const common = {
    occurredAt: now,
    actorLabel: "fixture-contextual:1",
    consentScopes: [],
    flowId: definition.flowId,
    sourceIds: [],
    sourceVersions: [],
    errorCode: null,
  };
  return [
    {
      ...common,
      eventId: "event-consent",
      sequence: 1,
      action: "consent-granted",
      tool: "change-consent",
      outcome: "active-consent",
    },
    {
      ...common,
      eventId: "event-context",
      sequence: 2,
      action: "context-category-accessed",
      tool: "read_consented_context",
      category: definition.fact.category,
      outcome: "accessed",
    },
    {
      ...common,
      eventId: "event-rule",
      sequence: 3,
      action: "rule-evaluated",
      tool: "evaluate_program_rules",
      ruleSetVersion: ruleVersion,
      ruleId: `${programId}-rule`,
      ruleVersion,
      sourceIds: [sourceId],
      sourceVersions: [{ sourceId, version: now }],
      outcome: "potential-match",
    },
    {
      ...common,
      eventId: "event-preview",
      sequence: 4,
      action: "preview-generated",
      tool: "build_application_preview",
      outcome: "review-required",
    },
    {
      ...common,
      eventId: "event-source",
      sequence: 5,
      action: "approved-source-accessed",
      tool: "search_approved_sources",
      sourceIds: [sourceId],
      sourceVersions: [{ sourceId, version: now }],
      outcome: "accessed",
    },
    {
      ...common,
      eventId: "event-handoff",
      sequence: 6,
      action: "handoff-offered",
      tool: "build_application_preview",
      sourceIds: [sourceId],
      sourceVersions: [{ sourceId, version: now }],
      outcome: "no-transfer",
    },
    {
      ...common,
      eventId: "event-terminal",
      sequence: 7,
      action: "context-run-completed",
      traceRef: "a".repeat(32),
      runRef: "b".repeat(64),
      tool: "context-run",
      ruleSetVersion: ruleVersion,
      outcome: "finished",
    },
  ];
}

function artifacts(definition) {
  const suffix = definition.flowId;
  const matches = definition.programs.map(([programId, sourceId]) => ({
    programId,
    status: "potential-match",
    ruleId: `${programId}-rule`,
    ruleVersion,
    policyEffectiveDate: "2026-10-28",
    satisfiedConditions: [`${programId}-context-present`],
    missingFacts: [],
    disqualifyingFacts: [],
    sourceIds: [sourceId],
    sourceVersions: [{ sourceId, version: now }],
    notice: "This is a screening indicator, not an eligibility decision.",
  }));
  const [field, label, value] = definition.previewField;
  return [
    {
      version: 1,
      id: `context-summary-${suffix}`,
      kind: "context-summary",
      payload: {
        personaLabel: definition.name,
        synthetic: true,
        purpose: definition.purpose,
        categories: definition.categories,
        facts: [{
          ...definition.fact,
          provenance: "synthetic-government-record",
          verifiedAt: now,
          mutableByCitizen: true,
          usedBy: [definition.flowId],
        }],
        missingFacts: ["official-service-confirmation"],
        consentExpiresAt: later,
      },
    },
    {
      version: 1,
      id: `program-matches-${suffix}`,
      kind: "program-matches",
      payload: matches,
    },
    {
      version: 1,
      id: `application-preview-${suffix}`,
      kind: "application-preview",
      payload: {
        previewId: `preview-${suffix}`,
        flowId: definition.flowId,
        schemaVersion: 1,
        fields: [
          {
            field,
            label,
            value,
            source: "synthetic-record",
            sourceFactKey: definition.fact.key,
            editable: true,
            sensitivity: "protected-b",
            requiresConfirmation: true,
          },
          {
            field: "official-service-confirmation",
            label: "Official service confirmation",
            value: null,
            source: "missing",
            sourceFactKey: null,
            editable: true,
            sensitivity: "personal",
            requiresConfirmation: true,
          },
        ],
        missingItems: ["Confirm remaining information with the official service."],
        submissionEnabled: false,
        requiresHumanReview: true,
        expiresAt: later,
      },
    },
    {
      version: 1,
      id: `consent-request-${suffix}`,
      kind: "consent-request",
      payload: {
        checkpointId: `checkpoint-${suffix}`,
        previewId: `preview-${suffix}`,
        purpose: definition.purpose,
        destinationName: definition.destinationName,
        destinationUrl: definition.destinationUrl,
        categoriesToShare: definition.categories,
        fieldNamesToShare: [field],
        transferMode: "none",
        reviewedByCitizen: false,
        submissionEnabled: false,
      },
    },
    {
      version: 1,
      id: `audit-receipt-${suffix}`,
      kind: "audit-receipt",
      payload: {
        receiptId: `audit-${suffix}`,
        sessionRef: `session-${suffix}`,
        personaLabel: definition.name,
        synthetic: true,
        events: auditEvents(definition),
        containsRawContextValues: false,
      },
    },
  ];
}

export const contextArtifactsByPersona = Object.fromEntries(
  Object.entries(definitions).map(([personaId, definition]) => [
    personaId,
    artifacts(definition),
  ]),
);

export async function installContextFixtureStream(page) {
  await page.addInitScript(({ fixtureArtifacts }) => {
    const original = window.fetch.bind(window);
    window.contextFixtureArtifacts = fixtureArtifacts;
    window.contextFixtureStreams = [];
    window.contextFixtureRequests = [];
    window.contextFixturePersona = null;
    window.fetch = async (input, init = {}) => {
      const url = typeof input === "string" ? input : input.url;
      if (url === "/api/demo/session" && init.method === "POST") {
        const request = JSON.parse(init.body);
        const response = await original(input, init);
        if (response.ok) window.contextFixturePersona = request.personaId;
        return response;
      }
      if (url === "/api/demo/session" && init.method === "DELETE") {
        const response = await original(input, init);
        if (response.ok) window.contextFixturePersona = null;
        return response;
      }
      if (url !== "/api/agent") return original(input, init);
      const request = JSON.parse(init.body);
      const headers = Object.fromEntries(new Headers(init.headers).entries());
      const encoder = new TextEncoder();
      const personaId = window.contextFixturePersona;
      window.contextFixtureRequests.push({ request, headers, personaId });
      return new Response(new ReadableStream({
        start(controller) {
          let closed = false;
          const stream = {
            request,
            headers,
            personaId,
            aborted: false,
            send(events) {
              if (!closed) {
                for (const event of events) {
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
                }
              }
            },
            finish() {
              if (closed) return;
              closed = true;
              controller.close();
            },
          };
          window.contextFixtureStreams.push(stream);
          init.signal?.addEventListener("abort", () => {
            stream.aborted = true;
            if (closed) return;
            closed = true;
            controller.error(new DOMException("Fixture response stopped", "AbortError"));
          }, { once: true });
        },
      }), { headers: { "content-type": "text/event-stream" } });
    };
  }, { fixtureArtifacts: contextArtifactsByPersona });
}

export async function completeContextFixture(page, index, text) {
  await page.waitForFunction(
    (expected) => window.contextFixtureStreams?.length > expected,
    index,
  );
  await page.evaluate(({ fixtureIndex, fixtureText }) => {
    const stream = window.contextFixtureStreams[fixtureIndex];
    const { runId, threadId } = stream.request;
    const contextual = stream.request.forwardedProps?.bc?.mode === "contextual-demo";
    const messageId = `context-fixture-answer-${fixtureIndex}`;
    const events = [
      { type: "RUN_STARTED", runId, threadId },
      {
        type: "CUSTOM",
        name: "bc.response",
        value: {
          version: 1,
          kind: contextual ? "grounded" : "dialogue",
          origin: "model",
        },
      },
      { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
      {
        type: "CUSTOM",
        name: "annotations",
        value: {
          messageId,
          annotations: [{
            url: "https://www2.gov.bc.ca/gov/content/home",
            title: "TEST FIXTURE reviewed B.C. source",
            publisher: "Government of British Columbia",
            documentId: "context-fixture",
            documentVersion: "v1",
          }],
        },
      },
      { type: "TEXT_MESSAGE_CONTENT", messageId, delta: fixtureText },
      { type: "TEXT_MESSAGE_END", messageId },
    ];
    if (contextual) {
      events.push(
        ...window.contextFixtureArtifacts[stream.personaId].map((artifact) => ({
          type: "CUSTOM",
          name: "bc.artifact",
          value: artifact,
        })),
      );
    }
    events.push({ type: "RUN_FINISHED", runId, threadId });
    stream.send(events);
    stream.finish();
  }, { fixtureIndex: index, fixtureText: text });
}
