const returns = (label, args, value) => ({ label, args, value });
const rejects = (label, args) => ({ label, args, throws: true });
const absent = (label, args) => ({ label, args, undefined: true });
const repository = "fixture/repo";
const run = (id, changes = {}) => ({
  id, name: "BC Gov Sources - Collection",
  path: ".github/workflows/official-source-collection.yml",
  head_branch: "main", head_repository: { full_name: repository },
  event: "schedule", status: "completed", conclusion: "success", ...changes,
});
const issue = {
  number: 7, id: 700, title: "Synthetic bug", body: "Synthetic report",
  state: "open", user: { type: "User" }, labels: [{ name: "bug" }],
};
const pull = (changes = {}) => ({
  state: "closed", user: { type: "Bot" }, body: "<!-- bc-bug-fix:7 -->", ...changes,
});
const regression = "scripts/tests/example.test.mjs";
const context = { number: 7, baseSha: "a".repeat(40) };
const evidence = {
  issueNumber: 7, baseSha: context.baseSha, command: ["node", "--test", regression],
  beforeExitCode: 1, afterExitCode: 0, failureKind: "assertion",
  regressionFiles: [regression], beforeSummary: "Synthetic assertion failure",
  afterSummary: "Synthetic pass",
};
const group = {
  sourceId: "health", marker: "<!-- bc-source-watchdog:health -->",
  fingerprint: "a".repeat(64), actionable: true,
};
const fingerprint = (value) => `<!-- bc-source-fingerprint:${value.repeat(64)} -->`;
const sourceIssue = (changes = {}) => ({
  number: 3, state: "closed", user: { type: "Bot" }, title: "[Source freshness] health",
  body: `${group.marker}\n${fingerprint("b")}\nHistory:\n${fingerprint("a")}`, ...changes,
});
const update = (changes = {}) => ({
  ...group, issueNumber: 3, issueState: "closed", fingerprintMarker: fingerprint("a"), ...changes,
});

export const checks = {
  "strict-ports": [
    returns("empty-default", ["", 8000, "API_PORT"], 8000),
    ...["1024", "65535", "043000"].map((value) =>
      returns(`valid-${value}`, [value, 3000, "WEB_PORT"], Number(value))),
    ...["-1", "80", "65536", "3.5", "+3000", " 3000", "3000 ", "0x1000", "NaN", null].map((value, i) =>
      rejects(`invalid-${i}`, [value, 3000, "WEB_PORT"])),
  ],
  "loopback-settings": [
    returns("custom-loopback", [{ WEB_PORT: "43000", API_PORT: "44000", HOST: "0.0.0.0" }],
      { webPort: 43000, apiPort: 44000, webUrl: "http://127.0.0.1:43000", apiUrl: "http://127.0.0.1:44000" }),
    returns("empty-defaults", [{ WEB_PORT: "", API_PORT: "" }],
      { webPort: 3000, apiPort: 8000, webUrl: "http://127.0.0.1:3000", apiUrl: "http://127.0.0.1:8000" }),
    rejects("normalized-collision", [{ WEB_PORT: "03000", API_PORT: "3000" }]),
    rejects("api-default-collision", [{ API_PORT: "3000" }]),
    rejects("invalid-api", [{ API_PORT: "8000oops" }]),
    rejects("invalid-web", [{ WEB_PORT: "80" }]),
  ],
  "checkpoint-continuity": [
    ...["failure", "cancelled", null].map((conclusion) => {
      const latest = run(2, { conclusion, status: conclusion === null ? "in_progress" : "completed" });
      return returns(`latest-${conclusion}`, [[run(1), latest], 3, repository, "main"], latest);
    }),
    returns("historical-name", [[run(1, { name: "Official source collection", conclusion: "failure" })],
      2, repository, "main"], run(1, { name: "Official source collection", conclusion: "failure" })),
    returns("exclude-current", [[run(5), run(2)], 5, repository, "main"], run(2)),
    ...["queued", "waiting", "pending", "requested"].map((status) =>
      returns(`not-started-${status}`, [[run(1), run(2, { status })], 3, repository, "main"], run(1))),
    ...[
      { head_repository: { full_name: "untrusted/repo" } }, { head_branch: "feature" },
      { path: ".github/workflows/other.yml" }, { name: "Other collector" },
      { event: "pull_request" }, { event: "push" },
    ].map((change, i) => absent(`untrusted-${i}`, [[run(2, change)], 3, repository, "main"])),
    absent("empty-history", [[], 1, repository, "main"]),
    { ...returns("legacy-rejected-for-current-event",
      [run(1, { name: "Official source collection" }), repository, "main"], false),
      function: "trustedCollection" },
  ],
  "bug-deduplication": [
    returns("merged-bot-pr", [issue, {}, [pull({ merged_at: "2026-01-01T00:00:00Z" })]], false),
    returns("open-bot-pr", [issue, {}, [pull({ state: "open" })]], false),
    returns("bot-login", [issue, {}, [pull({ user: { type: "User", login: "repair[bot]" } })]], false),
    returns("human-pr", [issue, {}, [pull({ user: { type: "User" } })]], true),
    returns("different-marker", [issue, {}, [pull({ body: "<!-- bc-bug-fix:70 -->" })]], true),
    returns("bug-form", [{ ...issue, labels: [], title: "[Bug]: Synthetic",
      body: "### Bug report\n\nSynthetic report" }, {}, []], true),
    ...[{ state: "closed" }, { user: { type: "Bot" } }, { labels: [] },
      { pull_request: {} }, { number: 0 }].map((change, i) =>
      returns(`ineligible-report-${i}`, [{ ...issue, ...change }, {}, []], false)),
    ...[{ action: "edited" }, { action: "labeled", label: { name: "triage" } },
      { action: "opened", issue: { number: 8, id: 800 } }].map((event, i) =>
      returns(`ineligible-event-${i}`, [issue, event, []], false)),
    returns("matching-label", [issue, { action: "labeled", label: { name: "bug" }, issue }, []], true),
  ],
  "repair-evidence": [
    absent("valid-evidence", [evidence, context, [regression]]),
    ...[
      { beforeExitCode: 0 }, { beforeExitCode: -1 }, { beforeExitCode: 1.5 },
      { afterExitCode: 1 }, { baseSha: "b".repeat(40) }, { issueNumber: 8 },
      { failureKind: "import" }, { command: [] }, { command: ["curl", "https://example.invalid"] },
      { command: ["node", ""] }, { beforeSummary: " " }, { afterSummary: "x".repeat(4001) },
      { regressionFiles: [] }, { regressionFiles: ["scripts/tests/../outside.mjs"] },
    ].map((change, i) => rejects(`invalid-evidence-${i}`, [{ ...evidence, ...change }, context, [regression]])),
    rejects("unchanged-regression", [evidence, context, []]),
    rejects("missing-evidence", [null, context, [regression]]),
  ],
  "current-fingerprint": [
    returns("current-match", [[group], [sourceIssue({ body: `${group.marker}\n${fingerprint("a")}` })]], []),
    returns("reverted-finding", [[group], [sourceIssue()]], [update()]),
    rejects("duplicate-source-issues", [[group], [sourceIssue(), sourceIssue({ number: 4 })]]),
    rejects("renamed-owned-issue", [[group], [sourceIssue({ title: "Other title" })]]),
    returns("no-new-benign-issue", [[{ ...group, actionable: false }], []], []),
    returns("recovered-closed-issue", [[{ ...group, actionable: false }], [sourceIssue()]],
      [update({ actionable: false })]),
    ...[
      { user: { type: "User" } }, { pull_request: {} },
      { body: "<!-- bc-source-watchdog:other -->" },
    ].map((change, i) => returns(`not-owned-${i}`, [[group], [sourceIssue(change)]],
      [update({ issueNumber: null, issueState: null })])),
  ],
};
