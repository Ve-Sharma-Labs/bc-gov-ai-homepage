import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BaseEvent } from "@ag-ui/core";
import { describe, expect, it, vi } from "vitest";
import { Conversation, resolveCitation } from "@/components/conversation";
import { SourceCard } from "@/components/sources";
import { evidenceMetadataSchema, localEvidenceMetadataSchema, sourceSchema } from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { initialStreamState, streamReducer, type StreamState } from "@/lib/stream";
import { catalogFixture, evidenceMetadataFixture } from "./fixtures";

const url = "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/03075_01";
const event = (state: StreamState, value: object) => streamReducer(state, {
  type: "event", runId: "run-1", event: value as BaseEvent,
});
const start = () => streamReducer(initialStreamState, { type: "start", runId: "run-1", messageId: "user-1", prompt: "TEST FIXTURE question" });
function annotated(metadata?: unknown, nested = false) {
  let state = event(start(), { type: "CUSTOM", name: "annotations", value: {
    messageId: "answer-1",
    annotations: [nested ? { url_citation: { url, metadata } } : { url, metadata }],
  } });
  return event(state, { type: "TEXT_MESSAGE_START", messageId: "answer-1", role: "assistant" });
}

describe("versioned evidence provenance", () => {
  it("keeps local evidence separate from human-approved indexed metadata", () => {
    const metadata = localEvidenceMetadataSchema.parse({
      version: 2, sourceIds: ["bc-laws"], documentType: "legal",
      retrievalOrigin: "official-live", useScope: "local-noncommercial-evaluation",
      humanReviewed: false, contentHash: "a".repeat(64),
      licenceUrl: "https://www.bclaws.gov.bc.ca/standards/Licence.html",
      attribution: "Synthetic Province of British Columbia fixture",
      notice: "Synthetic licence notice: THESE MATERIALS ARE NOT AN OFFICIAL VERSION.",
      consolidationDate: "2026-10-27", legalStatus: "publisher-current-collection",
    });
    expect(annotated(metadata).messages[1].citations[0].metadata).toEqual(metadata);
    for (const patch of [
      { humanReviewed: true }, { useScope: "public" }, { effectiveFrom: "2026-10-27" },
      { legalStatus: "in-force" }, { retrievalOrigin: "official-snapshot" },
    ]) {
      expect(evidenceMetadataSchema.safeParse({ ...metadata, ...patch }).success).toBe(false);
    }
  });

  it("shows the complete legal licence notice without opening a source dialog", () => {
    const metadata = localEvidenceMetadataSchema.parse({
      version: 2, sourceIds: ["bc-laws"], documentType: "legal",
      retrievalOrigin: "official-live", useScope: "local-noncommercial-evaluation",
      humanReviewed: false, contentHash: "a".repeat(64),
      licenceUrl: "https://www.bclaws.gov.bc.ca/standards/Licence.html",
      attribution: "Synthetic legal source attribution",
      notice: "Synthetic complete licence notice: THESE MATERIALS ARE NOT AN OFFICIAL VERSION.",
      consolidationDate: "2026-10-27", legalStatus: "publisher-current-collection",
    });
    let state = annotated(metadata);
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "A synthetic answer." });
    state = event(state, { type: "RUN_FINISHED" });
    render(<Conversation state={state} catalog={null} textFirst />);
    expect(screen.getByRole("complementary", { name: "Source licence notice" })).toBeVisible();
    expect(screen.getByText(metadata.notice)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("accepts the exact metadata and keeps omitted/null legacy references compatible", () => {
    expect(evidenceMetadataSchema.parse(evidenceMetadataFixture)).toEqual(evidenceMetadataFixture);
    expect(sourceSchema.parse(catalogFixture.sources[0]).metadata).toBeUndefined();
    expect(sourceSchema.parse({ ...catalogFixture.sources[0], metadata: null }).metadata).toBeNull();
    expect(sourceSchema.parse({ ...catalogFixture.sources[0], metadata: evidenceMetadataFixture }).metadata).toEqual(evidenceMetadataFixture);
    expect(annotated().messages[1].citations[0].metadata).toBeUndefined();
    expect(annotated(null).messages[1].citations[0].metadata).toBeNull();
  });

  it.each([
    ["version", { version: 2 }],
    ["document type", { documentType: "whole-site" }],
    ["missing review hash", { reviewHash: undefined }],
    ["short content hash", { contentHash: "a".repeat(40) }],
    ["invalid extraction hash", { extractionHash: "g".repeat(64) }],
    ["long rights hash", { rightsHash: "d".repeat(65) }],
    ["missing rights review", { rightsReviewId: "" }],
    ["empty source IDs", { sourceIds: [] }],
    ["duplicate source IDs", { sourceIds: ["bc-laws", "bc-laws"] }],
    ["invalid source identifier", { sourceIds: ["<script>"] }],
    ["invalid calendar date", { effectiveFrom: "2026-02-30" }],
    ["calendar timestamp", { consolidationDate: "2026-10-25T00:00:00Z" }],
    ["empty effective interval", { effectiveTo: "2026-10-24" }],
    ["inverted effective interval", { effectiveTo: "2026-10-23" }],
    ["invented legal status", { legalStatus: "verified-current" }],
    ["non-boolean historical flag", { isHistorical: "false" }],
    ["unversioned authority field", { wholeSiteReviewed: true }],
  ] as const)("rejects %s without discarding the safe official reference", (_name, patch) => {
    const metadata = { ...evidenceMetadataFixture, ...patch };
    expect(evidenceMetadataSchema.safeParse(metadata).success).toBe(false);
    const citation = annotated(metadata).messages[1].citations[0];
    expect(citation.url).toBe(url);
    expect(citation.metadata).toBeUndefined();
  });

  it("parses flat and native nested metadata without exposing it as a client instruction", () => {
    for (const nested of [false, true]) {
      const citation = annotated(evidenceMetadataFixture, nested).messages[1].citations[0];
      expect(citation.metadata).toEqual(evidenceMetadataFixture);
      expect(resolveCitation(citation, null, 0)?.metadata).toEqual(evidenceMetadataFixture);
    }
  });

  it("accepts late provenance on a completed source without changing the answer", () => {
    let state = annotated(null);
    state = event(state, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-1", delta: "TEST FIXTURE answer" });
    state = event(state, { type: "RUN_FINISHED" });
    state = event(state, { type: "CUSTOM", name: "annotations", value: {
      messageId: "answer-1", annotations: [{ url, metadata: evidenceMetadataFixture }],
    } });
    expect(state.status).toBe("complete");
    expect(state.messages[1].content).toBe("TEST FIXTURE answer");
    expect(state.messages[1].citations).toHaveLength(1);
    expect(state.messages[1].citations[0].metadata).toEqual(evidenceMetadataFixture);
  });

  it("never transfers catalogue-wide provenance onto a citation that did not supply it", () => {
    const catalog = {
      ...catalogFixture,
      sources: [{ ...catalogFixture.sources[0], metadata: evidenceMetadataFixture }],
    };
    const source = resolveCitation({
      sourceId: catalog.sources[0].id, url: "https://www.icbc.com/driver-licensing/visit-a-dl-office",
    }, catalog, 0);
    expect(source?.metadata).toBeNull();
  });
});

describe("source provenance details", () => {
  it("identifies dated copies and their author without claiming live or human review", async () => {
    const metadata = localEvidenceMetadataSchema.parse({
      version: 2, sourceIds: ["employment-insurance"], documentType: "guidance",
      retrievalOrigin: "official-snapshot", useScope: "local-noncommercial-evaluation",
      humanReviewed: false, contentHash: "b".repeat(64),
      licenceUrl: "https://www.canada.ca/en/transparency/terms.html",
      attribution: "EI Regular Benefits. Employment and Social Development Canada. Canada.ca.",
      notice: "This is a copy of the version available at the cited official URL.",
      consolidationDate: null, legalStatus: null,
    });
    const source = resolveCitation({
      sourceId: catalogFixture.sources[0].id, url: catalogFixture.sources[0].url,
      title: "Synthetic source copy", publisher: "Synthetic copy publisher", metadata,
    }, catalogFixture, 0)!;
    expect(source.publisher).toBe("Synthetic copy publisher");
    render(<SourceCard source={source} />);
    expect(screen.getByText("Dated copy of an official page", { selector: ".source-status" })).toBeVisible();
    await userEvent.setup().click(screen.getByText(source.title));
    expect(screen.getByText(metadata.attribution)).toBeVisible();
    expect(screen.getByText("Not human-reviewed for publication")).toBeVisible();
    expect(screen.queryByText("In force")).not.toBeInTheDocument();
  });

  it("separates effective bounds, consolidation and historical status, with snapshot-only review details", async () => {
    const user = userEvent.setup();
    const source = sourceSchema.parse({
      ...catalogFixture.sources[0], title: "TEST FIXTURE legal reference", url,
      metadata: evidenceMetadataFixture,
    });
    const { container } = render(<SourceCard source={source} />);
    await user.click(screen.getByText(source.title));
    expect(screen.getByText("Legal document")).toBeVisible();
    expect(screen.getByText("Effective from (inclusive)").nextElementSibling).toHaveTextContent("2026-10-24");
    expect(screen.getByText("Effective to (exclusive)").nextElementSibling).toHaveTextContent("2027-01-01");
    expect(screen.getByText("Consolidation date").nextElementSibling).toHaveTextContent("2026-10-25");
    expect(screen.getByText("Historical snapshot").nextElementSibling).toHaveTextContent("No");
    expect(screen.queryByText("Repealed on")).not.toBeInTheDocument();
    expect(container.querySelector('time[datetime="2026-10-24"]')).toHaveTextContent("2026-10-24");
    await user.click(screen.getByText("Review provenance"));
    expect(screen.getByText(/not whole-site coverage/)).toBeVisible();
    expect(screen.getByText("Source registry IDs").nextElementSibling).toHaveTextContent("bc-laws");
    expect(screen.getByText("Rights review").nextElementSibling).toHaveTextContent("TEST-FIXTURE-rights-review");
    expect(container.querySelectorAll(".source-provenance code")).toHaveLength(4);
    expect(screen.getByText(evidenceMetadataFixture.contentHash)).toBeVisible();
  });

  it("does not infer dates, historical status or provenance for legacy/guidance records", () => {
    const { rerender } = render(<SourceCard source={catalogFixture.sources[0]} />);
    expect(screen.queryByText("Review provenance")).not.toBeInTheDocument();
    rerender(<SourceCard source={{ ...catalogFixture.sources[0], metadata: null }} />);
    expect(screen.queryByText("Review provenance")).not.toBeInTheDocument();
    rerender(<SourceCard source={{
      ...catalogFixture.sources[0],
      metadata: {
        ...evidenceMetadataFixture, documentType: "guidance", language: null, legalStatus: null,
        effectiveFrom: null, effectiveTo: null, consolidationDate: null, repealedAt: null,
        legalSectionId: null, isHistorical: null,
      },
    }} />);
    for (const label of ["Language", "Legal status", "Effective from (inclusive)", "Effective to (exclusive)", "Consolidation date", "Historical snapshot"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("renders provenance identifiers only as escaped text, never HTML or executable links", () => {
    const { container } = render(<SourceCard source={{
      ...catalogFixture.sources[0],
      metadata: { ...evidenceMetadataFixture, rightsReviewId: "<img src=x onerror=alert(1)>", legalSectionId: "<script>alert(1)</script>" },
    }} />);
    expect(container.querySelectorAll("img, script, iframe")).toHaveLength(0);
    expect(container.querySelectorAll("a")).toHaveLength(1);
    expect(container.querySelector("a")).toHaveAttribute("href", catalogFixture.sources[0].url);
  });

  it("formats calendar-only dates in UTC rather than shifting to the previous B.C. day", () => {
    const formatter = vi.spyOn(Intl, "DateTimeFormat");
    expect(formatDate("2026-10-24")).toContain("24");
    expect(formatter).toHaveBeenLastCalledWith("en-CA", expect.objectContaining({ timeZone: "UTC" }));
    expect(formatDate("2026-10-24T00:00:00Z")).toContain("23");
    expect(formatter).toHaveBeenLastCalledWith("en-CA", expect.objectContaining({ timeZone: "America/Vancouver" }));
  });
});
