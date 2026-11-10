import { z } from "zod";
import { evidenceMetadataSchema, journeyIdSchema } from "./contract";
import { safeOfficialUrl } from "./links";

const id = z.string().min(1).max(100).regex(/^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$/);
const timestamp = z.string().datetime({ offset: true });
const url = z.string().max(2048).refine((value) => !!safeOfficialUrl(value));
export const researchActionSchema = z.enum(["corpus-explore", "web-check"]);
export const researchProgressSchema = z.object({
  version: z.literal(1), phase: z.enum(["retrieving", "summarizing"]),
}).strict();
export const researchGeographySchema = z.enum([
  "british-columbia", "vancouver", "victoria", "kelowna", "kamloops", "prince-george",
]);
export const researchOfferSchema = z.object({
  version: z.literal(1),
  parentRunId: id,
  parentMessageId: id,
  threadId: id,
  topics: z.array(journeyIdSchema).min(1).max(3),
  actions: z.array(researchActionSchema).min(1).max(2),
  expiresAt: timestamp,
}).strict();
const researchReferenceSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("indexed"),
    retrievedAt: timestamp,
    reference: z.object({
      sourceId: id, documentId: id, documentVersion: z.string().max(12000),
      title: z.string().max(12000), publisher: z.string().max(12000), url,
      checkedAt: z.string().max(80), publisherUpdatedAt: z.string().max(80).nullable(),
      section: z.string().max(1000), chunkId: id.nullable(),
      metadata: evidenceMetadataSchema.nullable(),
    }).strict(),
  }).strict(),
  z.object({
    kind: z.literal("web"), sourceId: id, title: z.string().min(1).max(500),
    publisher: z.string().min(1).max(500), url, retrievedAt: timestamp,
    crawledAt: timestamp.nullable(), publisherUpdatedAt: timestamp.nullable(),
    method: z.enum(["search", "browse"]), humanReviewed: z.literal(false),
    quoteLimit: z.number().int().min(1).max(200),
  }).strict(),
]);
export const researchResultSchema = z.object({
  version: z.literal(1), action: researchActionSchema, runId: id,
  parentRunId: id, parentMessageId: id, text: z.string().min(1).max(12000),
  citations: z.array(researchReferenceSchema).min(1).max(5), notice: z.string().max(600),
}).strict().superRefine((result, context) => {
  const kind = result.action === "web-check" ? "web" : "indexed";
  if (result.citations.some((citation) => citation.kind !== kind)) {
    context.addIssue({ code: "custom", message: "Research provenance does not match the selected action" });
  }
});

export type ResearchAction = z.infer<typeof researchActionSchema>;
export type ResearchGeography = z.infer<typeof researchGeographySchema>;
export type ResearchOffer = z.infer<typeof researchOfferSchema>;
export type ResearchResult = z.infer<typeof researchResultSchema>;
