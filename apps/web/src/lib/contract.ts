import { z } from "zod";

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
export const chatModeSchema = z.enum(["general", "pathway"]);
const runOptionFields = {
  journeyId: journeyIdSchema.nullable().optional(),
  researchRequested: z.boolean().optional(),
};
export const runOptionsSchema = z.union([
  z.object({ version: z.literal(1), ...runOptionFields }).strict(),
  z.object({ version: z.literal(2), mode: chatModeSchema, ...runOptionFields }).strict().superRefine((options, context) => {
    if (options.mode === "general" && options.journeyId != null) {
      context.addIssue({ code: "custom", message: "General chat cannot retain a hidden pathway scope" });
    }
    if (options.mode === "pathway" && options.journeyId == null) {
      context.addIssue({ code: "custom", message: "Pathway mode requires a supported journey" });
    }
  }),
]);
export const responseContextSchema = z.object({
  version: z.literal(1),
  kind: z.enum(["dialogue", "grounded", "handoff"]),
  origin: z.enum(["application", "model"]),
}).strict();
const text = z.string().max(12_000);
const id = z.string().min(1).max(160);
const isoDate = z.union([z.string().date(), z.string().datetime({ offset: true })]);
const date = isoDate.nullable();
const calendarDate = z.string().date().nullable();
const sha256 = z.string().regex(/^[a-f0-9]{64}$/);

export const evidenceMetadataSchema = z.object({
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

export const capabilitiesSchema = z.object({
  mode: z.enum(["guided", "foundry"]),
  aiConfigured: z.boolean(),
  webIqEnabled: z.boolean(),
  transactionsEnabled: z.literal(false),
  message: text,
  journeys: z.record(journeyIdSchema, z.boolean()).optional(),
  generalChatConfigured: z.boolean().optional(),
  retrievalReady: z.boolean().optional(),
  requestVersions: z.array(z.union([z.literal(1), z.literal(2)])).max(2).optional(),
});

export const progressSchema = z.object({
  version: z.literal(1).optional(),
  phase: z.enum(["connecting", "retrieving", "thinking", "preparing", "locations", "validating"]),
  message: z.string().max(300).optional(),
}).strict();

export const artifactSchema = z.discriminatedUnion("kind", [
  z.object({
    version: z.literal(1),
    id,
    kind: z.literal("preparation"),
    journey: journeySchema,
    sources: z.array(sourceSchema).max(100),
    transactionsEnabled: z.literal(false),
  }).strict(),
  z.object({
    version: z.literal(1),
    id,
    kind: z.literal("locations"),
    locations: z.array(locationSchema).max(100),
    sources: z.array(sourceSchema).max(100),
    notice: z.string().max(500),
  }).strict(),
]);

export type JourneyId = z.infer<typeof journeyIdSchema>;
export type ChatMode = z.infer<typeof chatModeSchema>;
export type RunOptions = z.infer<typeof runOptionsSchema>;
export type ResponseContext = z.infer<typeof responseContextSchema>;
export type EvidenceMetadata = z.infer<typeof evidenceMetadataSchema>;
export type ChatArtifact = z.infer<typeof artifactSchema>;
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
  message: "AI answers need the Azure / Microsoft Foundry connection. You can still explore source-backed guided plans.",
};
