import { z } from "zod";
import { safeOfficialUrl } from "./links";

const contractId = z.string().min(1).max(100).regex(/^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$/);
export const conversationFactKeySchema = z.enum([
  "licence-jurisdiction", "road-test-kind", "housing-need", "coverage-need",
  "primary-care-need", "service-need", "age-range", "phn-status", "bc-residency",
  "care-recipient", "priority",
]);
export const conversationCommandSchema = z.object({
  action: z.enum(["respond", "skip", "general", "correct", "remove", "explore", "sharing"]),
  revision: z.number().int().nonnegative(),
  questionId: contractId.nullable().optional(),
  factKey: conversationFactKeySchema.nullable().optional(),
  noticeVersion: z.literal("ai-conversation-v1"),
  shareContext: z.boolean(),
}).strict().superRefine((command, context) => {
  if (["correct", "remove"].includes(command.action) !== (command.factKey != null)) {
    context.addIssue({ code: "custom", message: "Only corrections/removals may name a fact" });
  }
  if (command.action === "skip" && !command.questionId) {
    context.addIssue({ code: "custom", message: "Skipping requires a pending question" });
  }
  if (!["respond", "skip"].includes(command.action) && command.questionId != null) {
    context.addIssue({ code: "custom", message: "This command cannot answer a question" });
  }
});
export const discoveryFactKeySchema = z.enum([
  "age", "licence-experience", "timeframe", "priority", "bc-residency", "phn-status", "support-for",
]);
export const discoveryCommandSchema = z.object({
  action: z.enum(["respond", "skip", "general", "correct", "remove", "explore", "refine"]).default("respond"),
  revision: z.number().int().nonnegative(),
  questionId: contractId.nullable().optional(),
  factKey: discoveryFactKeySchema.nullable().optional(),
}).strict().superRefine((command, context) => {
  if (["correct", "remove"].includes(command.action) !== (command.factKey != null)) {
    context.addIssue({ code: "custom", message: "Only a correction or removal may name a fact" });
  }
  if (command.action === "skip" && command.questionId == null) {
    context.addIssue({ code: "custom", message: "Skipping requires the current question" });
  }
  if (!["respond", "skip"].includes(command.action) && command.questionId != null) {
    context.addIssue({ code: "custom", message: "This command cannot answer a question" });
  }
});

export const journeyIds = [
  "licence-renewal",
  "road-test-booking",
  "rental-assistance",
  "health-coverage",
  "pharmacare-registration",
  "primary-care",
  "service-bc",
] as const;

export const journeyIdSchema = z.enum(journeyIds);
export const chatModeSchema = z.enum(["general", "pathway", "contextual-demo"]);
const runOptionFields = {
  journeyId: journeyIdSchema.nullable().optional(),
  researchRequested: z.boolean().optional(),
};
export const runOptionsSchema = z.union([
  z.object({
    version: z.union([z.literal(5), z.literal(6)]), mode: z.literal("general"), conversation: conversationCommandSchema,
    journeyId: z.null().optional(), researchRequested: z.literal(false).optional(),
  }).strict(),
  z.object({ version: z.literal(1), ...runOptionFields }).strict(),
  z.object({ version: z.literal(2), mode: z.enum(["general", "pathway"]), ...runOptionFields }).strict().superRefine((options, context) => {
    if (options.mode === "general" && options.journeyId != null) {
      context.addIssue({ code: "custom", message: "General chat cannot retain a hidden pathway scope" });
    }
    if (options.mode === "pathway" && options.journeyId == null) {
      context.addIssue({ code: "custom", message: "Pathway mode requires a supported journey" });
    }
  }),
  z.object({
    version: z.literal(3),
    mode: z.literal("contextual-demo"),
    researchRequested: z.literal(false).optional(),
  }).strict(),
  z.object({
    version: z.literal(4),
    mode: z.literal("general"),
    discovery: discoveryCommandSchema,
    journeyId: z.null().optional(),
    researchRequested: z.literal(false).optional(),
  }).strict(),
]);
export const responseContextSchema = z.object({
  version: z.literal(1),
  kind: z.enum(["dialogue", "grounded", "handoff"]),
  origin: z.enum(["application", "model"]),
  decisionOrigin: z.enum(["application", "model"]).optional(),
}).strict();
const text = z.string().max(12_000);
const id = z.string().min(1).max(160);
const isoDate = z.union([z.string().date(), z.string().datetime({ offset: true })]);
const date = isoDate.nullable();
const calendarDate = z.string().date().nullable();
const sha256 = z.string().regex(/^[a-f0-9]{64}$/);
const serviceKey = z.string().min(1).max(80).regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
const isoDateTime = z.string().datetime({ offset: true });

const indexedEvidenceMetadataSchema = z.object({
  version: z.literal(1),
  sourceIds: z.array(z.string().min(1).max(100).regex(/^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$/)).min(1).max(30),
  documentType: z.enum(["guidance", "legal", "service-directory", "notice"]),
  language: z.string().max(80).nullable(),
  contentHash: sha256,
  extractionHash: sha256,
  reviewHash: sha256,
  rightsReviewId: z.string().min(1).max(200),
  rightsHash: sha256,
  legalStatus: z.enum(["in-force", "not-yet-in-force", "repealed", "historical", "unknown"]).nullable(),
  effectiveFrom: calendarDate,
  effectiveTo: calendarDate,
  consolidationDate: calendarDate,
  repealedAt: calendarDate,
  legalSectionId: z.string().max(1000).nullable(),
  isHistorical: z.boolean().nullable(),
}).strict().superRefine((metadata, context) => {
  if (new Set(metadata.sourceIds).size !== metadata.sourceIds.length) {
    context.addIssue({ code: "custom", message: "Evidence source tags must be unique" });
  }
  if (metadata.effectiveFrom && metadata.effectiveTo && metadata.effectiveTo <= metadata.effectiveFrom) {
    context.addIssue({ code: "custom", message: "Legal intervals have an inclusive start and exclusive end" });
  }
});

export const localEvidenceMetadataSchema = z.object({
  version: z.literal(2),
  sourceIds: z.array(contractId).min(1).max(30),
  documentType: z.enum(["guidance", "legal", "service-directory"]),
  retrievalOrigin: z.enum(["official-live", "official-snapshot", "project-catalogue"]),
  useScope: z.literal("local-noncommercial-evaluation"),
  humanReviewed: z.literal(false),
  contentHash: sha256,
  licenceUrl: z.string().max(2048).refine((url) => !!safeOfficialUrl(url)).nullable(),
  attribution: z.string().min(1).max(2000),
  notice: z.string().min(1).max(3000),
  consolidationDate: calendarDate,
  legalStatus: z.literal("publisher-current-collection").nullable(),
}).strict().superRefine((metadata, context) => {
  if (new Set(metadata.sourceIds).size !== metadata.sourceIds.length) {
    context.addIssue({ code: "custom", message: "Evidence source tags must be unique" });
  }
  if (metadata.documentType === "legal" && (
    !metadata.consolidationDate || !metadata.legalStatus
    || metadata.retrievalOrigin !== "official-live" || !metadata.licenceUrl
  )) {
    context.addIssue({ code: "custom", message: "Legal evidence needs explicit current-collection provenance" });
  }
});

export const evidenceMetadataSchema = z.union([indexedEvidenceMetadataSchema, localEvidenceMetadataSchema]);

export const sourceSchema = z.object({
  id,
  title: text,
  publisher: text,
  url: z.string().max(2048),
  description: text,
  checkedAt: date,
  publisherUpdatedAt: date,
  status: z.enum(["available", "limited", "pending", "blocked"]),
  topics: z.array(text).max(40),
  metadata: evidenceMetadataSchema.nullable().optional(),
});

export const journeySchema = z.object({
  id: journeyIdSchema,
  title: text,
  prompt: text,
  summary: text,
  category: text,
  notice: text,
  sourceIds: z.array(id).max(80),
  steps: z.array(z.object({
    id,
    title: text,
    description: text,
    sourceIds: z.array(id).max(40),
  })).max(40),
  handoffs: z.array(z.object({
    label: text,
    url: z.string().max(2048),
    description: text,
    sourceIds: z.array(id).max(40),
  })).max(20),
});

export const locationSchema = z.object({
  id,
  name: text,
  municipality: text,
  address: text,
  hours: text,
  services: z.array(text).max(80),
  excludedServices: z.array(text).max(80),
  sourceIds: z.array(id).max(40),
  checkedAt: date,
});

export const catalogSchema = z.object({
  schemaVersion: z.literal(1),
  asOf: isoDate,
  sources: z.array(sourceSchema).max(500),
  journeys: z.array(journeySchema).max(7),
  locations: z.array(locationSchema).max(500),
}).superRefine((catalog, context) => {
  const sourceIds = new Set(catalog.sources.map((source) => source.id));
  const uniqueJourneys = new Set(catalog.journeys.map((journey) => journey.id));
  if (uniqueJourneys.size !== catalog.journeys.length || sourceIds.size !== catalog.sources.length) {
    context.addIssue({ code: "custom", message: "Duplicate catalogue identifiers" });
  }
  const referenced = [
    ...catalog.journeys.flatMap((journey) => [
      ...journey.sourceIds,
      ...journey.steps.flatMap((step) => step.sourceIds),
      ...journey.handoffs.flatMap((handoff) => handoff.sourceIds),
    ]),
    ...catalog.locations.flatMap((location) => location.sourceIds),
  ];
  if (referenced.some((sourceId) => !sourceIds.has(sourceId))) {
    context.addIssue({ code: "custom", message: "Unresolved catalogue source" });
  }
});

export const demoPersonaIds = [
  "maya-caregiver",
  "alex-disability-support",
  "sam-job-loss",
] as const;
export const demoPersonaIdSchema = z.enum(demoPersonaIds);

export const conversationGoalSchema = z.enum([
  "licence-renewal", "road-test-booking", "rental-assistance", "health-coverage",
  "pharmacare-registration", "primary-care", "service-bc", "motorcycle", "tenancy",
  "job-loss", "caregiving", "disability", "business", "bceid", "taxes", "laws", "general", "unknown",
]);
export const conversationSummarySchema = z.object({
  version: z.literal(1), noticeVersion: z.literal("ai-conversation-v1"),
  threadId: contractId, revision: z.number().int().min(1), expiresAt: isoDateTime,
  goal: conversationGoalSchema, goalLabel: z.string().min(1).max(100),
  subject: z.enum(["you", "someone-else", "unspecified"]),
  phase: z.enum(["clarify", "guide", "answer", "handoff", "social"]),
  questionCount: z.number().int().min(0).max(3),
  question: z.object({
    id: contractId, kind: z.enum(["intent", "context"]),
    factKey: conversationFactKeySchema.nullable(),
    text: z.string().min(1).max(500), reason: z.string().min(1).max(500),
    choices: z.array(z.string().min(1).max(100)).max(5),
    candidates: z.array(conversationGoalSchema).max(3), personal: z.boolean(),
  }).strict().nullable(),
  facts: z.array(z.object({
    key: conversationFactKeySchema, label: z.string().min(1).max(100),
    value: z.enum([
      "bc", "other", "car", "motorcycle", "rent", "tenancy", "housing", "msp", "pharmacare",
      "both", "find-provider", "contact-provider", "licensing", "income-support", "identity",
      "general-service", "under-19", "19-or-older", "yes", "no", "moving", "adult", "child", "work",
    ]).nullable(),
    displayValue: z.string().min(1).max(100),
    status: z.enum(["provided", "unknown", "declined", "disputed"]),
    subject: z.enum(["you", "someone-else", "unspecified"]),
    provenance: z.literal("citizen-answer"), personal: z.boolean(),
  }).strict()).max(11),
  shareContext: z.boolean(), journeyId: journeyIdSchema.nullable(),
  suggestedDemoId: demoPersonaIdSchema.nullable(),
  limitation: z.enum(["none", "uncertain-intent", "missing-context", "source-coverage", "outside-scope"]),
  decisionOrigin: z.enum(["model", "application"]),
}).strict().superRefine((summary, context) => {
  if (new Set(summary.facts.map((fact) => fact.key)).size !== summary.facts.length) {
    context.addIssue({ code: "custom", message: "Conversation facts must be unique" });
  }
  if ((summary.phase === "clarify") !== (summary.question !== null)) {
    context.addIssue({ code: "custom", message: "Clarification requires one question" });
  }
  if (!summary.shareContext && (summary.facts.some((fact) => fact.personal) || summary.question?.personal)) {
    context.addIssue({ code: "custom", message: "Personal context requires optional sharing" });
  }
  if (summary.facts.some((fact) => (fact.status === "provided") !== (fact.value !== null))) {
    context.addIssue({ code: "custom", message: "Only explicit answers have a value" });
  }
});

export const assistanceTaskSchema = z.object({
  id: contractId, journeyId: journeyIdSchema, catalogVersion: sha256,
  stepVersions: z.record(contractId, sha256),
  stepIds: z.array(contractId).min(1).max(40), activeStepId: contractId,
  reviewedStepIds: z.array(contractId).max(40), skippedStepIds: z.array(contractId).max(40),
  phase: z.enum(["preparing", "ready-for-official-handoff"]),
  waitingFor: z.enum(["readiness", "municipality", "official-service"]),
  lastAction: z.enum(["continue", "explain", "reviewed", "next", "back", "skip", "repair", "full-guide"]),
  municipality: z.string().min(1).max(100).nullable(),
  service: z.enum(["icbc-licensing", "income-assistance", "bc-services-card", "bceid"]).nullable(),
}).strict().superRefine((task, context) => {
  if (!task.stepIds.includes(task.activeStepId)
    || task.reviewedStepIds.some((id) => !task.stepIds.includes(id) || task.skippedStepIds.includes(id))
    || task.skippedStepIds.some((id) => !task.stepIds.includes(id))
    || [task.stepIds, task.reviewedStepIds, task.skippedStepIds].some((ids) => new Set(ids).size !== ids.length)) {
    context.addIssue({ code: "custom", message: "Task progress must reference unique existing steps" });
  }
});
export const taskSnapshotSchema = z.object({
  version: z.literal(1), threadId: contractId, revision: z.number().int().min(1),
  task: assistanceTaskSchema.nullable(),
  step: journeySchema.shape.steps.element.nullable(),
  handoffs: journeySchema.shape.handoffs,
  sources: z.array(sourceSchema).max(100),
  guidance: z.string().max(8000),
}).strict().superRefine((snapshot, context) => {
  if (snapshot.task?.activeStepId !== snapshot.step?.id) {
    context.addIssue({ code: "custom", message: "Current step must match the active task" });
  }
});
export const conversationControlSchema = z.object({
  id: contractId, revision: z.number().int().min(1), noticeVersion: z.literal("ai-conversation-v1"),
  action: z.enum(["sharing", "review", "next", "back", "skip"]),
  shareContext: z.boolean().nullable().optional(), taskId: contractId.nullable().optional(),
  stepId: contractId.nullable().optional(), reviewed: z.boolean().nullable().optional(),
}).strict().superRefine((control, context) => {
  if (control.action === "sharing" ? control.shareContext == null || control.taskId != null || control.stepId != null || control.reviewed != null
    : control.taskId == null || control.stepId == null || control.shareContext != null) {
    context.addIssue({ code: "custom", message: "Only the requested setting or task step may change" });
  }
  if ((control.action === "review") !== (control.reviewed != null)) {
    context.addIssue({ code: "custom", message: "Only review controls specify reviewed status" });
  }
});
export const conversationControlResponseSchema = z.object({
  summary: conversationSummarySchema, task: taskSnapshotSchema, notice: z.string().min(1).max(500),
}).strict().superRefine((response, context) => {
  if (response.summary.threadId !== response.task.threadId || response.summary.revision !== response.task.revision) {
    context.addIssue({ code: "custom", message: "Control snapshots must be consistent" });
  }
});

export const discoveryFactSchema = z.object({
  key: discoveryFactKeySchema,
  label: z.string().min(1).max(100),
  value: z.string().min(1).max(100).nullable(),
  status: z.enum(["provided", "unknown", "declined", "disputed"]),
  provenance: z.literal("citizen-answer"),
}).strict().superRefine((fact, context) => {
  if ((fact.status === "provided") !== (fact.value !== null)) {
    context.addIssue({ code: "custom", message: "Only an explicit answer may supply a fact value" });
  }
});
export const discoverySummarySchema = z.object({
  version: z.literal(1),
  threadId: contractId,
  revision: z.number().int().min(1),
  phase: z.enum(["understand", "plan"]),
  goalId: z.enum([
    "motorcycle", "licence", "road-test", "rent", "health", "pharmacare",
    "primary-care", "service-bc", "job-loss", "caregiving", "disability",
  ]).nullable(),
  goalLabel: z.string().min(1).max(100),
  about: z.enum(["you", "someone-else", "unspecified"]),
  questionCount: z.number().int().min(0).max(3),
  facts: z.array(discoveryFactSchema).max(7),
  question: z.object({
    id: contractId,
    factKey: discoveryFactKeySchema,
    text: z.string().min(1).max(500),
    reason: z.string().min(1).max(500),
    choices: z.array(z.string().min(1).max(100)).max(6),
  }).strict().nullable(),
  suggestions: z.array(z.object({
    journeyId: journeyIdSchema,
    reason: z.string().min(1).max(300),
  }).strict()).max(3),
  suggestedDemoId: demoPersonaIdSchema.nullable(),
  expiresAt: isoDateTime,
}).strict().superRefine((summary, context) => {
  if (new Set(summary.facts.map((fact) => fact.key)).size !== summary.facts.length
    || new Set(summary.suggestions.map((item) => item.journeyId)).size !== summary.suggestions.length) {
    context.addIssue({ code: "custom", message: "Discovery facts and suggestions must be unique" });
  }
  if (summary.question && (summary.phase !== "understand" || !summary.goalId)) {
    context.addIssue({ code: "custom", message: "A question requires a current discovery goal" });
  }
  if (summary.phase !== "plan" && (summary.suggestions.length || summary.suggestedDemoId)) {
    context.addIssue({ code: "custom", message: "Recommendations follow discovery" });
  }
});

export const contextCategories = [
  "identity-residency",
  "household-dependants",
  "employment-income",
  "disability-caregiving",
  "existing-programs",
  "region-preferences",
] as const;
export const contextCategorySchema = z.enum(contextCategories);
export const factProvenanceSchema = z.enum([
  "synthetic-government-record",
  "citizen-answer",
]);
export const factSensitivitySchema = z.enum([
  "personal",
  "protected-a",
  "protected-b",
]);

export const consentScopes = [
  "identity.read",
  "household.read",
  "employment.read",
  "disability-caregiving.read",
  "existing-programs.read",
  "region-preferences.read",
] as const;
export const consentScopeSchema = z.enum(consentScopes);
const scopeByCategory = {
  "identity-residency": "identity.read",
  "household-dependants": "household.read",
  "employment-income": "employment.read",
  "disability-caregiving": "disability-caregiving.read",
  "existing-programs": "existing-programs.read",
  "region-preferences": "region-preferences.read",
} as const;
const contextValueSchema = z.union([
  z.string().min(1).max(1000),
  z.number().finite(),
  z.boolean(),
]);
const previewValueSchema = contextValueSchema.nullable();

export const demoPersonaSummarySchema = z.object({
  id: demoPersonaIdSchema,
  displayName: z.string().min(1).max(80),
  summary: z.string().min(1).max(500),
  availableCategories: z.array(contextCategorySchema).min(1).max(6),
  synthetic: z.literal(true),
}).strict().superRefine((persona, context) => {
  if (new Set(persona.availableCategories).size !== persona.availableCategories.length) {
    context.addIssue({ code: "custom", message: "Persona categories must be unique" });
  }
});

export const contextFactSchema = z.object({
  key: contractId,
  value: contextValueSchema,
  category: contextCategorySchema,
  source: serviceKey,
  provenance: factProvenanceSchema,
  verifiedAt: isoDateTime,
  sensitivity: factSensitivitySchema,
  consentScope: consentScopeSchema,
  mutableByCitizen: z.boolean(),
}).strict().superRefine((fact, context) => {
  if (scopeByCategory[fact.category] !== fact.consentScope) {
    context.addIssue({ code: "custom", message: "The fact scope must match its category" });
  }
  if (fact.provenance === "synthetic-government-record" && !fact.source.startsWith("synthetic-")) {
    context.addIssue({ code: "custom", message: "Synthetic facts require a synthetic source" });
  }
  if (fact.provenance === "citizen-answer" && fact.source !== "citizen-answer") {
    context.addIssue({ code: "custom", message: "Citizen answers require the citizen-answer source" });
  }
});

export const contextSummaryFactSchema = z.object({
  key: contractId,
  label: z.string().min(1).max(120),
  category: contextCategorySchema,
  displayValue: z.string().min(1).max(500),
  provenance: factProvenanceSchema,
  verifiedAt: isoDateTime,
  mutableByCitizen: z.boolean(),
  usedBy: z.array(contractId).max(20),
}).strict().superRefine((fact, context) => {
  if (new Set(fact.usedBy).size !== fact.usedBy.length) {
    context.addIssue({ code: "custom", message: "Context fact consumers must be unique" });
  }
});

export const contextSummarySchema = z.object({
  personaLabel: z.string().min(1).max(120),
  synthetic: z.literal(true),
  purpose: serviceKey,
  categories: z.array(contextCategorySchema).min(1).max(6),
  facts: z.array(contextSummaryFactSchema).max(50),
  missingFacts: z.array(contractId).max(30),
  consentExpiresAt: isoDateTime,
}).strict().superRefine((summary, context) => {
  if (new Set(summary.categories).size !== summary.categories.length) {
    context.addIssue({ code: "custom", message: "Context summary categories must be unique" });
  }
  const factKeys = summary.facts.map((fact) => fact.key);
  if (new Set(factKeys).size !== factKeys.length) {
    context.addIssue({ code: "custom", message: "Context summary fact keys must be unique" });
  }
  if (new Set(summary.missingFacts).size !== summary.missingFacts.length) {
    context.addIssue({ code: "custom", message: "Missing context facts must be unique" });
  }
  if (summary.facts.some((fact) => !summary.categories.includes(fact.category))) {
    context.addIssue({ code: "custom", message: "Every fact must belong to a disclosed category" });
  }
  if (summary.missingFacts.some((key) => factKeys.includes(key))) {
    context.addIssue({ code: "custom", message: "A fact cannot be both present and missing" });
  }
});

export const consentScopeProposalSchema = z.object({
  scope: consentScopeSchema,
  category: contextCategorySchema,
  reason: z.string().min(1).max(300),
  required: z.boolean(),
}).strict().superRefine((proposal, context) => {
  if (scopeByCategory[proposal.category] !== proposal.scope) {
    context.addIssue({ code: "custom", message: "The proposed scope must match its category" });
  }
});

export const consentProposalSchema = z.object({
  proposalId: contractId,
  personaId: demoPersonaIdSchema,
  purpose: serviceKey,
  noticeVersion: contractId,
  scopes: z.array(consentScopeProposalSchema).min(1).max(6),
  expiresAt: isoDateTime,
  synthetic: z.literal(true),
}).strict().superRefine((proposal, context) => {
  const scopes = proposal.scopes.map((item) => item.scope);
  const categories = proposal.scopes.map((item) => item.category);
  if (new Set(scopes).size !== scopes.length || new Set(categories).size !== categories.length) {
    context.addIssue({ code: "custom", message: "Proposed scopes and categories must be unique" });
  }
});

export const consentReceiptSchema = z.object({
  consentId: contractId,
  purpose: serviceKey,
  scopes: z.array(consentScopeSchema).min(1).max(6),
  subjectHash: z.string().min(8).max(128).regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/),
  noticeVersion: contractId,
  grantedAt: isoDateTime,
  expiresAt: isoDateTime,
  revokedAt: isoDateTime.nullable(),
}).strict().superRefine((receipt, context) => {
  if (new Set(receipt.scopes).size !== receipt.scopes.length) {
    context.addIssue({ code: "custom", message: "Consent scopes must be unique" });
  }
  const granted = Date.parse(receipt.grantedAt);
  const expires = Date.parse(receipt.expiresAt);
  if (expires <= granted) {
    context.addIssue({ code: "custom", message: "Consent expiry must follow its grant" });
  }
  if (receipt.revokedAt) {
    const revoked = Date.parse(receipt.revokedAt);
    if (revoked < granted || revoked > expires) {
      context.addIssue({ code: "custom", message: "Consent revocation must be within its lifetime" });
    }
  }
});

export const consentRevocationSchema = z.object({
  revocationId: contractId,
  consentId: contractId,
  revokedScopes: z.array(consentScopeSchema).min(1).max(6),
  revokedAt: isoDateTime,
  reason: z.enum(["citizen-request", "session-reset", "session-expired", "persona-changed"]),
}).strict().superRefine((revocation, context) => {
  if (new Set(revocation.revokedScopes).size !== revocation.revokedScopes.length) {
    context.addIssue({ code: "custom", message: "Revoked scopes must be unique" });
  }
});

export const programSourceVersionSchema = z.object({
  sourceId: contractId,
  version: contractId,
}).strict();
export const programMatchStatusSchema = z.enum([
  "potential-match",
  "needs-information",
  "already-enrolled",
  "not-indicated",
]);
export const screeningNotice = "This is a screening indicator, not an eligibility decision." as const;
export const programMatchSchema = z.object({
  programId: contractId,
  status: programMatchStatusSchema,
  ruleId: contractId.nullable().optional(),
  ruleVersion: contractId,
  policyEffectiveDate: z.string().date(),
  satisfiedConditions: z.array(contractId).max(30),
  missingFacts: z.array(contractId).max(30),
  disqualifyingFacts: z.array(contractId).max(30),
  sourceIds: z.array(contractId).min(1).max(20),
  sourceVersions: z.array(programSourceVersionSchema).min(1).max(20),
  notice: z.literal(screeningNotice),
}).strict().superRefine((match, context) => {
  const groups = [match.satisfiedConditions, match.missingFacts, match.disqualifyingFacts];
  if (groups.some((values) => new Set(values).size !== values.length)) {
    context.addIssue({ code: "custom", message: "Program match facts must be unique" });
  }
  if (
    groups[0].some((value) => groups[1].includes(value) || groups[2].includes(value))
    || groups[1].some((value) => groups[2].includes(value))
  ) {
    context.addIssue({ code: "custom", message: "Program match fact groups must not overlap" });
  }
  const sourceVersions = match.sourceVersions.map((source) => source.sourceId);
  if (
    new Set(match.sourceIds).size !== match.sourceIds.length
    || new Set(sourceVersions).size !== sourceVersions.length
    || match.sourceIds.some((sourceId, index) => sourceVersions[index] !== sourceId)
  ) {
    context.addIssue({ code: "custom", message: "Every source ID needs one matching version" });
  }
});
export const programMatchesSchema = z.array(programMatchSchema).min(1).max(20)
  .superRefine((matches, context) => {
    const ids = matches.map((match) => match.programId);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({ code: "custom", message: "Program IDs must be unique" });
    }
  });

export const previewFieldSchema = z.object({
  field: contractId,
  label: z.string().min(1).max(120),
  value: previewValueSchema,
  source: z.enum(["synthetic-record", "citizen-answer", "missing"]),
  sourceFactKey: contractId.nullable(),
  editable: z.boolean(),
  sensitivity: factSensitivitySchema,
  requiresConfirmation: z.boolean(),
}).strict().superRefine((field, context) => {
  if (field.source === "missing") {
    if (field.value !== null || field.sourceFactKey !== null) {
      context.addIssue({ code: "custom", message: "Missing fields cannot carry values or provenance" });
    }
  } else if (field.value === null || field.sourceFactKey === null) {
    context.addIssue({ code: "custom", message: "Populated fields require complete provenance" });
  }
});

export const applicationPreviewSchema = z.object({
  previewId: contractId,
  flowId: z.enum(["guardianship-intake", "disability-support", "job-loss"]),
  schemaVersion: z.literal(1),
  fields: z.array(previewFieldSchema).min(1).max(50),
  missingItems: z.array(z.string().min(1).max(500)).max(30),
  submissionEnabled: z.literal(false),
  requiresHumanReview: z.literal(true),
  expiresAt: isoDateTime,
}).strict().superRefine((preview, context) => {
  const fields = preview.fields.map((field) => field.field);
  if (new Set(fields).size !== fields.length) {
    context.addIssue({ code: "custom", message: "Preview fields must be unique" });
  }
  if (new Set(preview.missingItems).size !== preview.missingItems.length) {
    context.addIssue({ code: "custom", message: "Missing preview items must be unique" });
  }
});

export const consentRequestSchema = z.object({
  checkpointId: contractId,
  previewId: contractId,
  purpose: serviceKey,
  destinationName: z.string().min(1).max(160),
  destinationUrl: z.string().max(2048).refine((value) => safeOfficialUrl(value) !== null),
  categoriesToShare: z.array(contextCategorySchema).max(6),
  fieldNamesToShare: z.array(contractId).max(50),
  transferMode: z.literal("none"),
  reviewedByCitizen: z.boolean(),
  submissionEnabled: z.literal(false),
}).strict().superRefine((request, context) => {
  if (
    new Set(request.categoriesToShare).size !== request.categoriesToShare.length
    || new Set(request.fieldNamesToShare).size !== request.fieldNamesToShare.length
  ) {
    context.addIssue({ code: "custom", message: "Consent request fields must be unique" });
  }
});

export const auditActionSchema = z.enum([
  "consent-granted",
  "consent-revoked",
  "context-category-accessed",
  "rule-evaluated",
  "preview-generated",
  "approved-source-accessed",
  "handoff-offered",
  "handoff-opened",
  "access-denied",
  "session-cleared",
  "context-run-completed",
]);
export const contextAuditToolSchema = z.enum([
  "context-authorization",
  "change-consent",
  "clear-context",
  "read_consented_context",
  "evaluate_program_rules",
  "build_application_preview",
  "search_approved_sources",
  "context-run",
]);
export const auditOutcomeSchema = z.enum([
  "active-consent",
  "active-minimum-consent",
  "accessed",
  "potential-match",
  "needs-information",
  "already-enrolled",
  "not-indicated",
  "review-required",
  "no-transfer",
  "denied",
  "revoked-partial",
  "revoked-complete",
  "citizen-request",
  "session-reset",
  "persona-changed",
  "finished",
  "cancelled",
  "failed",
]);
const contextFlowIdSchema = z.enum([
  "guardianship-intake",
  "disability-support",
  "job-loss",
]);
export const auditReceiptEventSchema = z.object({
  eventId: contractId,
  sequence: z.number().int().min(1),
  occurredAt: isoDateTime,
  action: auditActionSchema,
  traceRef: z.string().min(16).max(128).regex(/^[a-f0-9]+$/).nullable().optional(),
  runRef: z.string().length(64).regex(/^[a-f0-9]{64}$/).nullable().optional(),
  actorLabel: z.string().min(1).max(160)
    .regex(/^[a-zA-Z0-9][a-zA-Z0-9_.:@-]*$/).nullable().optional(),
  tool: contextAuditToolSchema.nullable().optional(),
  consentScopes: z.array(consentScopeSchema).max(6).default([]),
  flowId: contextFlowIdSchema.nullable().optional(),
  ruleSetVersion: contractId.nullable().optional(),
  category: contextCategorySchema.nullable().optional(),
  ruleId: contractId.nullable().optional(),
  ruleVersion: contractId.nullable().optional(),
  sourceIds: z.array(contractId).max(20).default([]),
  sourceVersions: z.array(programSourceVersionSchema).max(20).default([]),
  outcome: auditOutcomeSchema,
  errorCode: z.string().max(80).regex(/^[A-Z][A-Z0-9_]*$/).nullable().optional(),
}).strict().superRefine((event, context) => {
  if (new Set(event.consentScopes).size !== event.consentScopes.length) {
    context.addIssue({ code: "custom", message: "Audit consent scopes must be unique" });
  }
  const sourceIds = event.sourceVersions.map((source) => source.sourceId);
  if (
    new Set(event.sourceIds).size !== event.sourceIds.length
    || new Set(sourceIds).size !== sourceIds.length
  ) {
    context.addIssue({ code: "custom", message: "Audit sources must be unique" });
  }
  if (
    sourceIds.length > 0
    && (
      event.sourceIds.length !== sourceIds.length
      || event.sourceIds.some((sourceId, index) => sourceIds[index] !== sourceId)
    )
  ) {
    context.addIssue({ code: "custom", message: "Every audit source needs one matching version" });
  }
  if (event.action === "context-category-accessed" && !event.category) {
    context.addIssue({ code: "custom", message: "Context access requires a category" });
  }
  if (
    event.action === "rule-evaluated"
    && (
      !event.ruleId
      || !event.ruleVersion
      || !event.ruleSetVersion
      || event.sourceIds.length === 0
      || event.sourceVersions.length === 0
    )
  ) {
    context.addIssue({ code: "custom", message: "Rule evaluation requires rule and source versions" });
  }
  if (event.action === "preview-generated" && !event.flowId) {
    context.addIssue({ code: "custom", message: "Preview generation requires a flow" });
  }
  if (event.action === "access-denied" && !event.errorCode) {
    context.addIssue({ code: "custom", message: "Denied access requires an error code" });
  }
  if (event.action === "context-run-completed" && (!event.traceRef || !event.runRef)) {
    context.addIssue({ code: "custom", message: "Run completion requires opaque references" });
  }
});
export const auditReceiptSchema = z.object({
  receiptId: contractId,
  sessionRef: contractId,
  personaLabel: z.string().min(1).max(120),
  synthetic: z.literal(true),
  events: z.array(auditReceiptEventSchema).min(1).max(100),
  containsRawContextValues: z.literal(false),
}).strict().superRefine((receipt, context) => {
  const ids = receipt.events.map((event) => event.eventId);
  if (new Set(ids).size !== ids.length) {
    context.addIssue({ code: "custom", message: "Audit event IDs must be unique" });
  }
  if (receipt.events.some((event, index) => event.sequence !== index + 1)) {
    context.addIssue({ code: "custom", message: "Audit events must be contiguous and ordered" });
  }
});

export const sourceHealthSchema = z.object({
  status: z.enum(["unknown", "ready", "expiring", "expired", "empty", "unusable", "unavailable"]),
  checkedAt: z.string().datetime({ offset: true }).nullable(),
  usableDocuments: z.number().int().nonnegative(),
  expiredDocuments: z.number().int().nonnegative(),
  rejectedChunks: z.number().int().nonnegative(),
  nextExpiryAt: z.string().datetime({ offset: true }).nullable(),
  coveredSourceIds: z.array(contractId).max(100),
  missingSourceIds: z.array(contractId).max(100),
  errorCode: z.string().regex(/^[A-Z][A-Z0-9_]{0,63}$/).nullable(),
});

export const capabilitiesSchema = z.object({
  mode: z.enum(["guided", "foundry"]),
  aiConfigured: z.boolean(),
  webIqEnabled: z.boolean(),
  transactionsEnabled: z.literal(false),
  message: text,
  journeys: z.record(journeyIdSchema, z.boolean()).optional(),
  generalChatConfigured: z.boolean().optional(),
  retrievalReady: z.boolean().optional(),
  sourceHealth: sourceHealthSchema.optional(),
  requestVersions: z.array(z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4), z.literal(5), z.literal(6)])).max(6).optional(),
  conversationAvailable: z.boolean().optional(),
  conversationAgentReady: z.boolean().optional(),
  taskAssistanceAvailable: z.boolean().optional(),
  localEvidenceEvaluation: z.boolean().optional(),
  discoveryAvailable: z.boolean().optional(),
  syntheticContextAvailable: z.boolean().optional(),
  realIdentityIntegrated: z.literal(false).optional(),
}).superRefine((capabilities, context) => {
  if (
    capabilities.requestVersions
    && new Set(capabilities.requestVersions).size !== capabilities.requestVersions.length
  ) {
    context.addIssue({ code: "custom", message: "Request versions must be unique" });
  }
  if (
    capabilities.syntheticContextAvailable
    && !capabilities.requestVersions?.includes(3)
  ) {
    context.addIssue({ code: "custom", message: "Synthetic context requires request version 3" });
  }
  if (!!capabilities.discoveryAvailable !== !!capabilities.requestVersions?.includes(4)) {
    context.addIssue({ code: "custom", message: "Discovery availability must match request version 4" });
  }
  if (!!capabilities.conversationAvailable !== !!capabilities.requestVersions?.includes(5)) {
    context.addIssue({ code: "custom", message: "AI conversation requires request version 5" });
  }
  if (capabilities.requestVersions?.includes(6) && !capabilities.taskAssistanceAvailable) {
    context.addIssue({ code: "custom", message: "Grounded conversation requires task support" });
  }
});

export const progressSchema = z.object({
  version: z.literal(1).optional(),
  phase: z.enum(["connecting", "retrieving", "thinking", "preparing", "locations", "validating"]),
  message: z.string().max(300).optional(),
}).strict();

const preparationArtifactSchema = z.object({
  version: z.literal(1),
  id,
  kind: z.literal("preparation"),
  journey: journeySchema,
  sources: z.array(sourceSchema).max(100),
  transactionsEnabled: z.literal(false),
}).strict();
const locationsArtifactSchema = z.object({
  version: z.literal(1),
  id,
  kind: z.literal("locations"),
  locations: z.array(locationSchema).max(100),
  sources: z.array(sourceSchema).max(100),
  notice: z.string().max(500),
}).strict();
const contextSummaryArtifactSchema = z.object({
  version: z.literal(1),
  id: contractId,
  kind: z.literal("context-summary"),
  payload: contextSummarySchema,
}).strict();
const programMatchesArtifactSchema = z.object({
  version: z.literal(1),
  id: contractId,
  kind: z.literal("program-matches"),
  payload: programMatchesSchema,
}).strict();
const applicationPreviewArtifactSchema = z.object({
  version: z.literal(1),
  id: contractId,
  kind: z.literal("application-preview"),
  payload: applicationPreviewSchema,
}).strict();
const consentRequestArtifactSchema = z.object({
  version: z.literal(1),
  id: contractId,
  kind: z.literal("consent-request"),
  payload: consentRequestSchema,
}).strict();
const auditReceiptArtifactSchema = z.object({
  version: z.literal(1),
  id: contractId,
  kind: z.literal("audit-receipt"),
  payload: auditReceiptSchema,
}).strict();

export const anonymousArtifactSchema = z.discriminatedUnion("kind", [
  preparationArtifactSchema,
  locationsArtifactSchema,
]);
export const contextArtifactSchema = z.discriminatedUnion("kind", [
  contextSummaryArtifactSchema,
  programMatchesArtifactSchema,
  applicationPreviewArtifactSchema,
  consentRequestArtifactSchema,
  auditReceiptArtifactSchema,
]);
export const artifactSchema = z.discriminatedUnion("kind", [
  preparationArtifactSchema,
  locationsArtifactSchema,
  contextSummaryArtifactSchema,
  programMatchesArtifactSchema,
  applicationPreviewArtifactSchema,
  consentRequestArtifactSchema,
  auditReceiptArtifactSchema,
]);
export const artifactListSchema = z.array(artifactSchema).max(10)
  .superRefine((artifacts, context) => {
    const ids = artifacts.map((artifact) => artifact.id);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({ code: "custom", message: "Artifact IDs must be unique" });
    }
  });

export type JourneyId = z.infer<typeof journeyIdSchema>;
export type ChatMode = z.infer<typeof chatModeSchema>;
export type RunOptions = z.infer<typeof runOptionsSchema>;
export type ResponseContext = z.infer<typeof responseContextSchema>;
export type DiscoveryCommand = z.infer<typeof discoveryCommandSchema>;
export type DiscoverySummary = z.infer<typeof discoverySummarySchema>;
export type DiscoveryFact = z.infer<typeof discoveryFactSchema>;
export type DiscoveryFactKey = z.infer<typeof discoveryFactKeySchema>;
export type ConversationCommand = z.infer<typeof conversationCommandSchema>;
export type ConversationFactKey = z.infer<typeof conversationFactKeySchema>;
export type ConversationSummary = z.infer<typeof conversationSummarySchema>;
export type TaskSnapshot = z.infer<typeof taskSnapshotSchema>;
export type ConversationControl = z.infer<typeof conversationControlSchema>;
export type ConversationControlResponse = z.infer<typeof conversationControlResponseSchema>;
export type EvidenceMetadata = z.infer<typeof evidenceMetadataSchema>;
export type DemoPersonaId = z.infer<typeof demoPersonaIdSchema>;
export type DemoPersonaSummary = z.infer<typeof demoPersonaSummarySchema>;
export type ContextCategory = z.infer<typeof contextCategorySchema>;
export type ContextFact = z.infer<typeof contextFactSchema>;
export type ContextSummary = z.infer<typeof contextSummarySchema>;
export type ContextSummaryFact = z.infer<typeof contextSummaryFactSchema>;
export type ConsentScope = z.infer<typeof consentScopeSchema>;
export type ConsentProposal = z.infer<typeof consentProposalSchema>;
export type ConsentReceipt = z.infer<typeof consentReceiptSchema>;
export type ConsentRevocation = z.infer<typeof consentRevocationSchema>;
export type ProgramMatch = z.infer<typeof programMatchSchema>;
export type ApplicationPreview = z.infer<typeof applicationPreviewSchema>;
export type ConsentRequest = z.infer<typeof consentRequestSchema>;
export type AuditReceipt = z.infer<typeof auditReceiptSchema>;
export type ContextArtifact = z.infer<typeof contextArtifactSchema>;
export type Artifact = z.infer<typeof artifactSchema>;
export type ChatArtifact = z.infer<typeof anonymousArtifactSchema>;
export type Source = z.infer<typeof sourceSchema>;
export type Journey = z.infer<typeof journeySchema>;
export type Location = z.infer<typeof locationSchema>;
export type Catalog = z.infer<typeof catalogSchema>;
export type Capabilities = z.infer<typeof capabilitiesSchema>;

export const unavailableCapabilities: Capabilities = {
  mode: "guided",
  aiConfigured: false,
  webIqEnabled: false,
  transactionsEnabled: false,
  syntheticContextAvailable: false,
  discoveryAvailable: false,
  realIdentityIntegrated: false,
  message: "AI answers need the Azure / Microsoft Foundry connection. You can still explore source-backed guided plans.",
};
