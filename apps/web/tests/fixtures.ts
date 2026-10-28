import { journeyIds, type Catalog, type Capabilities, type EvidenceMetadata } from "@/lib/contract";

const titles = {
  "licence-renewal": "Prepare a licence renewal",
  "road-test-booking": "Prepare to book a road test",
  "rental-assistance": "Explore rental assistance",
  "health-coverage": "Understand health coverage",
  "pharmacare-registration": "Register for Fair PharmaCare",
  "primary-care": "Find primary care",
  "service-bc": "Find a Service BC office",
};

// Synthetic records for tests only. Nothing in the shipped app imports this module.
export const catalogFixture: Catalog = {
  schemaVersion: 1,
  asOf: "2026-10-24",
  sources: [
    {
      id: "fixture-icbc",
      title: "Fixture licensing evidence",
      publisher: "ICBC",
      url: "https://www.icbc.com/driver-licensing",
      description: "TEST FIXTURE: limited dynamic content, verify with the official service.",
      checkedAt: "2026-10-24",
      publisherUpdatedAt: null,
      status: "limited",
      topics: ["licensing"],
    },
    {
      id: "fixture-service",
      title: "Fixture office evidence",
      publisher: "Service BC",
      url: "https://www2.gov.bc.ca/gov/content/home",
      description: "TEST FIXTURE: office capabilities are explicitly limited.",
      checkedAt: "2026-10-24",
      publisherUpdatedAt: null,
      status: "available",
      topics: ["offices"],
    },
  ],
  journeys: journeyIds.map((id) => ({
    id,
    title: titles[id],
    prompt: `TEST FIXTURE: help with ${id}`,
    summary: "TEST FIXTURE: prepare an informed next step using the official source.",
    category: "Test service",
    notice: "TEST FIXTURE: dated snapshot, not live availability.",
    sourceIds: ["fixture-icbc"],
    steps: [
      { id: "prepare", title: "Review the accepted identification guidance", description: "TEST FIXTURE: read the linked requirements. Do not enter ID numbers here.", sourceIds: ["fixture-icbc"] },
      { id: "confirm", title: "Confirm the service with the agency", description: "TEST FIXTURE: use an official handoff to verify the next step.", sourceIds: ["fixture-icbc"] },
    ],
    handoffs: [
      { label: "Open the official service", url: "https://www.icbc.com/driver-licensing", description: "TEST FIXTURE: nothing is submitted here.", sourceIds: ["fixture-icbc"] },
    ],
  })),
  locations: [
    {
      id: "fixture-office-a",
      name: "Fixture limited office",
      municipality: "Test Town",
      address: "TEST FIXTURE address",
      hours: "TEST FIXTURE published hours",
      services: ["icbc-licensing", "bceid"],
      excludedServices: ["icbc-licensing"],
      sourceIds: ["fixture-service"],
      checkedAt: "2026-10-24",
    },
    {
      id: "fixture-office-b",
      name: "Fixture licensing office",
      municipality: "Test Town",
      address: "TEST FIXTURE address",
      hours: "TEST FIXTURE published hours",
      services: ["icbc-licensing"],
      excludedServices: [],
      sourceIds: ["fixture-service"],
      checkedAt: null,
    },
  ],
};

export const guidedCapabilities: Capabilities = {
  mode: "guided",
  aiConfigured: false,
  webIqEnabled: false,
  transactionsEnabled: false,
  message: "TEST FIXTURE: native connection not configured.",
};

export const evidenceMetadataFixture: EvidenceMetadata = {
  version: 1,
  sourceIds: ["bc-laws"],
  documentType: "legal",
  language: "en-CA",
  contentHash: "a".repeat(64),
  extractionHash: "b".repeat(64),
  reviewHash: "c".repeat(64),
  rightsReviewId: "TEST-FIXTURE-rights-review",
  rightsHash: "d".repeat(64),
  legalStatus: "in-force",
  effectiveFrom: "2026-10-24",
  effectiveTo: "2027-01-01",
  consolidationDate: "2026-10-25",
  repealedAt: null,
  legalSectionId: "section-12",
  isHistorical: false,
};
