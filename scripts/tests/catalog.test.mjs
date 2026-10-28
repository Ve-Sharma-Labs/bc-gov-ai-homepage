import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { root } from "../runtime.mjs";

const catalogue = JSON.parse(readFileSync(path.join(root, "data", "pilot-catalog.json"), "utf8"));
const expectedJourneys = [
  "health-coverage", "licence-renewal", "pharmacare-registration", "primary-care",
  "rental-assistance", "road-test-booking", "service-bc",
];

function assertOfficialLink(value) {
  const url = new URL(value);
  assert.equal(url.protocol, "https:");
  assert.equal(url.username, "");
  assert.equal(url.password, "");
  assert.ok([
    "gov.bc.ca", "bchousing.org", "icbc.com", "workbc.ca", "healthlinkbc.ca",
  ].some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`)), value);
}

test("catalogue has the seven contracted journeys and all twelve source areas", () => {
  assert.equal(catalogue.schemaVersion, 1);
  assert.ok(Number.isFinite(Date.parse(catalogue.asOf)));
  assert.equal(catalogue.sources.length, 12);
  assert.equal(new Set(catalogue.sources.map((source) => source.id)).size, 12);
  assert.deepEqual(catalogue.journeys.map((journey) => journey.id).sort(), expectedJourneys);
});

test("every journey step and handoff carries resolvable source evidence", () => {
  const sources = new Set(catalogue.sources.map((source) => source.id));
  for (const journey of catalogue.journeys) {
    assert.ok(journey.notice.length > 0);
    assert.ok(journey.steps.length > 0);
    assert.ok(journey.handoffs.length > 0);
    for (const item of [journey, ...journey.steps, ...journey.handoffs]) {
      assert.ok(item.sourceIds.length > 0);
      for (const sourceId of item.sourceIds) assert.ok(sources.has(sourceId), sourceId);
    }
    for (const handoff of journey.handoffs) assertOfficialLink(handoff.url);
  }
});

test("source and location metadata preserve unknowns and safe public URLs", () => {
  const sources = new Set(catalogue.sources.map((source) => source.id));
  for (const source of catalogue.sources) {
    assertOfficialLink(source.url);
    assert.ok(["available", "limited", "pending", "blocked"].includes(source.status));
    for (const field of ["checkedAt", "publisherUpdatedAt"]) {
      assert.ok(source[field] === null || Number.isFinite(Date.parse(source[field])));
    }
  }
  for (const location of catalogue.locations) {
    assert.ok(location.sourceIds.every((id) => sources.has(id)));
    assert.ok(location.services.every((service) => !location.excludedServices.includes(service)));
    assert.ok(location.checkedAt === null || Number.isFinite(Date.parse(location.checkedAt)));
  }
});
