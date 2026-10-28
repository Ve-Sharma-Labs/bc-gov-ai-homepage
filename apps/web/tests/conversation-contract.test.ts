import { describe, expect, it } from "vitest";
import { capabilitiesSchema, responseContextSchema, runOptionsSchema } from "@/lib/contract";

describe("versioned conversation contract", () => {
  it.each([
    { version: 1 },
    { version: 1, journeyId: "service-bc" },
    { version: 2, mode: "general" },
    { version: 2, mode: "general", journeyId: null },
    { version: 2, mode: "pathway", journeyId: "health-coverage" },
  ])("accepts supported options %j", (options) => {
    expect(runOptionsSchema.safeParse(options).success).toBe(true);
  });

  it.each([
    { version: 1, mode: "general" },
    { version: 1, mode: null },
    { version: 2 },
    { version: 2, mode: "general", journeyId: "service-bc" },
    { version: 2, mode: "pathway" },
    { version: 2, mode: "pathway", journeyId: null },
    { version: 2, mode: "general", responseKind: "dialogue" },
    { version: 2, mode: "general", researchRequested: "false" },
    { version: true, mode: "general" },
  ])("rejects inconsistent or authority-changing options %j", (options) => {
    expect(runOptionsSchema.safeParse(options).success).toBe(false);
  });

  it("distinguishes response purpose from its origin", () => {
    expect(responseContextSchema.parse({
      version: 1, kind: "dialogue", origin: "application",
    })).toEqual({ version: 1, kind: "dialogue", origin: "application" });
    expect(responseContextSchema.safeParse({
      version: 1, kind: "dialogue", origin: "model", trusted: true,
    }).success).toBe(false);
  });

  it("can still read a legacy capabilities response", () => {
    const result = capabilitiesSchema.parse({
      mode: "guided", aiConfigured: false, webIqEnabled: false,
      transactionsEnabled: false, message: "Guided plans are available.",
    });
    expect(result.generalChatConfigured).toBeUndefined();
    expect(result.retrievalReady).toBeUndefined();
  });
});
