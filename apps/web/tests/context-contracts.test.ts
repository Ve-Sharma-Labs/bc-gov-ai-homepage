import { describe, expect, it } from "vitest";
import {
  applicationPreviewSchema,
  artifactListSchema,
  artifactSchema,
  auditReceiptSchema,
  capabilitiesSchema,
  consentProposalSchema,
  consentReceiptSchema,
  consentRequestSchema,
  consentRevocationSchema,
  contextFactSchema,
  demoPersonaSummarySchema,
  programMatchSchema,
  programMatchesSchema,
  runOptionsSchema,
  screeningNotice,
} from "@/lib/contract";

const now = "2026-10-28T20:00:00Z";
const later = "2026-10-28T20:30:00Z";

const match = {
  programId: "workbc-navigation",
  status: "potential-match",
  ruleId: "workbc-screening",
  ruleVersion: "2026-10-28.1",
  policyEffectiveDate: "2026-10-28",
  satisfiedConditions: ["bc-resident", "employment-ended"],
  missingFacts: ["preferred-service-channel"],
  disqualifyingFacts: [],
  sourceIds: ["workbc"],
  sourceVersions: [{ sourceId: "workbc", version: "2026-10-28" }],
  notice: screeningNotice,
} as const;

const preview = {
  previewId: "preview-sam-1",
  flowId: "job-loss",
  schemaVersion: 1,
  fields: [{
    field: "employment-status",
    label: "Employment status",
    value: "recently-ended",
    source: "synthetic-record",
    sourceFactKey: "employment.status",
    editable: true,
    sensitivity: "protected-b",
    requiresConfirmation: true,
  }],
  missingItems: ["Confirm the preferred service channel"],
  submissionEnabled: false,
  requiresHumanReview: true,
  expiresAt: later,
} as const;

const summary = {
  personaLabel: "Sam - recently lost a job",
  synthetic: true,
  purpose: "personalize-job-loss-navigation",
  categories: ["employment-income"],
  facts: [{
    key: "employment.status",
    label: "Employment status",
    category: "employment-income",
    displayValue: "Recently ended",
    provenance: "synthetic-government-record",
    verifiedAt: now,
    mutableByCitizen: true,
    usedBy: ["workbc-navigation"],
  }],
  missingFacts: ["preferred-service-channel"],
  consentExpiresAt: later,
} as const;

const consentRequest = {
  checkpointId: "checkpoint-sam-1",
  previewId: "preview-sam-1",
  purpose: "personalize-job-loss-navigation",
  destinationName: "WorkBC",
  destinationUrl: "https://www.workbc.ca/",
  categoriesToShare: ["employment-income"],
  fieldNamesToShare: ["employment-status"],
  transferMode: "none",
  reviewedByCitizen: false,
  submissionEnabled: false,
} as const;

const audit = {
  receiptId: "audit-sam-1",
  sessionRef: "session-sam-1",
  personaLabel: "Sam - recently lost a job",
  synthetic: true,
  events: [{
    eventId: "event-rule-1",
    sequence: 1,
    occurredAt: now,
    action: "rule-evaluated",
    traceRef: "a".repeat(32),
    runRef: "b".repeat(64),
    actorLabel: "test-contextual:1",
    tool: "evaluate_program_rules",
    consentScopes: ["employment.read"],
    flowId: "job-loss",
    ruleSetVersion: "2026-10-28.1",
    category: null,
    ruleId: "workbc-screening",
    ruleVersion: "2026-10-28.1",
    sourceIds: ["workbc"],
    sourceVersions: [{ sourceId: "workbc", version: "2026-10-28" }],
    outcome: "potential-match",
    errorCode: null,
  }],
  containsRawContextValues: false,
} as const;

describe("citizen context contracts", () => {
  it("allowlists synthetic personas and validates fact provenance", () => {
    expect(demoPersonaSummarySchema.safeParse({
      id: "sam-job-loss",
      displayName: "Sam - recently lost a job",
      summary: "A fictional job-loss navigation scenario.",
      availableCategories: ["employment-income", "region-preferences"],
      synthetic: true,
    }).success).toBe(true);
    expect(demoPersonaSummarySchema.safeParse({
      id: "other-persona",
      displayName: "Other",
      summary: "Not allowlisted.",
      availableCategories: ["employment-income"],
      synthetic: true,
    }).success).toBe(false);

    const fact = {
      key: "employment.status",
      value: "recently-ended",
      category: "employment-income",
      source: "synthetic-employment-system",
      provenance: "synthetic-government-record",
      verifiedAt: now,
      sensitivity: "protected-b",
      consentScope: "employment.read",
      mutableByCitizen: true,
    };
    expect(contextFactSchema.safeParse(fact).success).toBe(true);
    expect(contextFactSchema.safeParse({ ...fact, source: "employment-system" }).success).toBe(false);
    expect(contextFactSchema.safeParse({ ...fact, consentScope: "identity.read" }).success).toBe(false);
    expect(contextFactSchema.safeParse({ ...fact, rawRecord: { unsafe: true } }).success).toBe(false);
  });

  it("keeps consent purpose-bound, unique, revocable and time-bounded", () => {
    const scope = {
      scope: "employment.read",
      category: "employment-income",
      reason: "Use the fictional job-loss status.",
      required: true,
    } as const;
    const proposal = {
      proposalId: "proposal-sam-1",
      personaId: "sam-job-loss",
      purpose: "personalize-job-loss-navigation",
      noticeVersion: "1",
      scopes: [scope],
      expiresAt: later,
      synthetic: true,
    } as const;
    expect(consentProposalSchema.safeParse(proposal).success).toBe(true);
    expect(consentProposalSchema.safeParse({ ...proposal, scopes: [scope, scope] }).success).toBe(false);

    const receipt = {
      consentId: "consent-sam-1",
      purpose: "personalize-job-loss-navigation",
      scopes: ["employment.read"],
      subjectHash: "non-reversible-reference",
      noticeVersion: "1",
      grantedAt: now,
      expiresAt: later,
      revokedAt: null,
    } as const;
    expect(consentReceiptSchema.safeParse(receipt).success).toBe(true);
    expect(consentReceiptSchema.safeParse({ ...receipt, expiresAt: now }).success).toBe(false);
    expect(consentRevocationSchema.safeParse({
      revocationId: "revocation-sam-1",
      consentId: receipt.consentId,
      revokedScopes: ["employment.read"],
      revokedAt: later,
      reason: "citizen-request",
    }).success).toBe(true);
  });

  it("preserves deterministic match versions and preview provenance", () => {
    expect(programMatchSchema.safeParse(match).success).toBe(true);
    expect(programMatchSchema.safeParse({
      ...match,
      sourceVersions: [{ sourceId: "different-source", version: "2026-10-28" }],
    }).success).toBe(false);
    expect(programMatchSchema.safeParse({
      ...match,
      missingFacts: ["bc-resident"],
    }).success).toBe(false);
    expect(programMatchesSchema.safeParse([match, match]).success).toBe(false);

    expect(applicationPreviewSchema.safeParse(preview).success).toBe(true);
    expect(applicationPreviewSchema.safeParse({ ...preview, submissionEnabled: true }).success).toBe(false);
    expect(applicationPreviewSchema.safeParse({
      ...preview,
      fields: [preview.fields[0], preview.fields[0]],
    }).success).toBe(false);
    expect(applicationPreviewSchema.safeParse({
      ...preview,
      fields: [{ ...preview.fields[0], source: "missing" }],
    }).success).toBe(false);
  });

  it("defines five strict AG-UI context artifacts with unique IDs", () => {
    const artifacts = [
      { version: 1, id: "artifact-summary-1", kind: "context-summary", payload: summary },
      { version: 1, id: "artifact-matches-1", kind: "program-matches", payload: [match] },
      { version: 1, id: "artifact-preview-1", kind: "application-preview", payload: preview },
      { version: 1, id: "artifact-consent-1", kind: "consent-request", payload: consentRequest },
      { version: 1, id: "artifact-audit-1", kind: "audit-receipt", payload: audit },
    ] as const;
    expect(artifacts.every((artifact) => artifactSchema.safeParse(artifact).success)).toBe(true);
    expect(artifactListSchema.safeParse(artifacts).success).toBe(true);
    expect(artifactListSchema.safeParse([...artifacts, { ...artifacts[0] }]).success).toBe(false);
    expect(artifactSchema.safeParse({
      ...artifacts[0],
      execute: { tool: "submit" },
    }).success).toBe(false);
  });

  it("keeps handoff and audit receipts non-transactional and value-free", () => {
    expect(consentRequestSchema.safeParse(consentRequest).success).toBe(true);
    expect(consentRequestSchema.safeParse({
      ...consentRequest,
      transferMode: "post",
      submissionEnabled: true,
    }).success).toBe(false);
    expect(auditReceiptSchema.safeParse(audit).success).toBe(true);
    expect(auditReceiptSchema.safeParse({
      ...audit,
      containsRawContextValues: true,
    }).success).toBe(false);
    expect(auditReceiptSchema.safeParse({
      ...audit,
      events: [{ ...audit.events[0], sequence: 2 }],
    }).success).toBe(false);
  });

  it("uses version 3 for contextual demo routing without accepting client facts", () => {
    expect(runOptionsSchema.safeParse({ version: 3, mode: "contextual-demo" }).success).toBe(true);
    for (const options of [
      { version: 3, mode: "general" },
      { version: 3, mode: "contextual-demo", journeyId: "service-bc" },
      { version: 3, mode: "contextual-demo", researchRequested: true },
      { version: 3, mode: "contextual-demo", facts: [{ key: "forged" }] },
    ]) {
      expect(runOptionsSchema.safeParse(options).success).toBe(false);
    }
  });

  it("advertises synthetic availability without claiming identity integration", () => {
    const capabilities = capabilitiesSchema.parse({
      mode: "guided",
      aiConfigured: false,
      webIqEnabled: false,
      transactionsEnabled: false,
      message: "Synthetic context is not enabled.",
      requestVersions: [1, 2, 3],
      syntheticContextAvailable: false,
      realIdentityIntegrated: false,
    });
    expect(capabilities.syntheticContextAvailable).toBe(false);
    expect(capabilities.realIdentityIntegrated).toBe(false);
  });
});
