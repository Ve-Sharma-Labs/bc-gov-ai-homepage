import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { formatDate, safeOfficialUrl, sourceNeedsReview } from "@/lib/links";
import { OfficialLink } from "@/components/official-link";
import { resolveCitation, SafeMarkdown } from "@/components/conversation";
import { catalogFixture } from "./fixtures";

describe("official destination validation", () => {
  it.each([
    "javascript:alert(1)", "data:text/html,<h1>bad</h1>", "//www.icbc.com",
    "http://www.icbc.com", "https://www.icbc.com.evil.test", "https://evil-icbc.com",
    "https://user@www.icbc.com", "https://www.icbc.com:444", "https://www.icbc.com\\@evil.test",
    "https://www.icbc.com\n.evil.test", "/api/agent", "https://example.com",
  ])("blocks %s", (url) => expect(safeOfficialUrl(url)).toBeNull());

  it.each(["https://www.icbc.com/driver-licensing", "https://www2.gov.bc.ca/gov/content/home", "https://www.healthlinkbc.ca/health-connect-registry", "https://www.bchousing.org/housing-assistance"])("allows %s", (url) => expect(safeOfficialUrl(url)).toBe(url));

  it("tells people when a handoff opens another tab", () => {
    render(<OfficialLink href="https://www.icbc.com">Continue at ICBC</OfficialLink>);
    const link = screen.getByRole("link", { name: /Continue at ICBC.*opens in a new tab/u });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("never renders executable HTML, images or unsafe Markdown links", () => {
    const { container } = render(<SafeMarkdown>{"Hello <script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![track](https://example.com/image)\n\n[ICBC](https://www.icbc.com)"}</SafeMarkdown>);
    expect(container.querySelectorAll("script, iframe, img")).toHaveLength(0);
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://www.icbc.com/");
  });
});

describe("source date honesty", () => {
  it("opens the actual cited page instead of substituting its publisher catalogue root", () => {
    const source = catalogFixture.sources[0];
    const url = "https://www.icbc.com/driver-licensing/visit-a-dl-office";
    const result = resolveCitation({ sourceId: source.id, url, title: "Specific official page", documentId: "office-guidance", documentVersion: "v1" }, catalogFixture, 0);
    expect(result?.url).toBe(url);
    expect(result?.title).toBe("Specific official page");
  });
  it("does not invent missing or invalid dates", () => {
    expect(formatDate(null)).toBe("Not provided");
    expect(formatDate("not-a-date")).toBe("Not provided");
    expect(formatDate("2026-10-24")).toContain("24");
  });
  it("labels limited, old and unknown evidence for review", () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    expect(sourceNeedsReview({ status: "available", checkedAt: "2026-10-23" }, now)).toBe(false);
    expect(sourceNeedsReview({ status: "available", checkedAt: "2026-10-01" }, now)).toBe(true);
    expect(sourceNeedsReview({ status: "available", checkedAt: null }, now)).toBe(true);
    expect(sourceNeedsReview({ status: "blocked", checkedAt: "2026-10-23" }, now)).toBe(true);
  });
});
