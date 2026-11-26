import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { siteDescription, siteMetadata, siteTitle, siteUrl, socialImageAlt } from "@/app/site-metadata";

vi.mock("next/og", () => ({
  ImageResponse: vi.fn(function ImageResponse() {}),
}));

const socialImageRoutes = [
  { name: "Open Graph", load: () => import("@/app/opengraph-image") },
  { name: "Twitter", load: () => import("@/app/twitter-image") },
];

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Social-image inputs must not fetch remote assets.")));
});

afterEach(() => {
  vi.doUnmock("node:fs/promises");
});

describe("site link metadata", () => {
  it("brands the canonical site as BC.Gov", () => {
    expect(siteMetadata.metadataBase).toEqual(siteUrl);
    expect(siteMetadata.title).toEqual({ default: siteTitle, template: "%s · BC.Gov" });
    expect(siteMetadata.description).toBe(siteDescription);
    expect(siteMetadata.alternates).toEqual({ canonical: "/" });
    expect(siteMetadata.robots).toEqual({ index: false, follow: false });
  });

  it("publishes matching Open Graph and Twitter cards", async () => {
    const [openGraph, twitter] = await Promise.all(socialImageRoutes.map(({ load }) => load()));
    expect(siteMetadata.openGraph).toMatchObject({
      type: "website",
      url: "/",
      title: "BC.Gov",
      description: siteDescription,
      siteName: "BC.Gov",
      locale: "en_CA",
      images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: socialImageAlt }],
    });
    expect(siteMetadata.twitter).toMatchObject({
      card: "summary_large_image",
      title: "BC.Gov",
      description: siteDescription,
      images: [{ url: "/twitter-image", width: 1200, height: 630, alt: socialImageAlt }],
    });
    expect(openGraph.size).toEqual({ width: 1200, height: 630 });
    expect(twitter.size).toEqual(openGraph.size);
    expect(openGraph.alt).toBe(socialImageAlt);
    expect(twitter.alt).toBe(socialImageAlt);
    expect(openGraph.contentType).toBe("image/png");
    expect(twitter.contentType).toBe(openGraph.contentType);
  });
});

describe.each(socialImageRoutes)("$name social-image inputs", ({ load }) => {
  it("passes the real bundled logo to ImageResponse without fetching it", async () => {
    const route = await load();
    await route.default();

    expect(ImageResponse).toHaveBeenCalledTimes(1);
    const [card, options] = vi.mocked(ImageResponse).mock.calls[0];
    expect(options).toEqual({ width: 1200, height: 630 });

    // Inspect the shared card input, not ImageResponse's PNG rendering.
    const container = document.createElement("div");
    container.innerHTML = renderToStaticMarkup(card);
    const logos = container.querySelectorAll("img");
    expect(logos).toHaveLength(1);
    const logo = logos[0];
    const src = logo.getAttribute("src")!;
    expect(src).toMatch(/^data:image\/png;base64,/);
    expect(src).not.toMatch(/^https?:\/\//);
    const logoBytes = Buffer.from(src.slice("data:image/png;base64,".length), "base64");
    expect(logoBytes).toEqual(readFileSync(join(process.cwd(), "public", "brand", "bc-logo-horizontal-transparent.png")));
    expect(logoBytes.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    expect(logoBytes.readUInt32BE(16)).toBe(361);
    expect(logoBytes.readUInt32BE(20)).toBe(120);
    expect(logo.alt).toBe("Government of British Columbia");
    expect(logo.style.width).toBe("361px");
    expect(logo.style.height).toBe("120px");
    expect(container.textContent).toContain(siteTitle);
    expect(container.textContent).toContain("Government services, made easier to navigate.");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["ENOENT", "EACCES"])("propagates %s instead of returning an unbranded image", async (code) => {
    const failure = Object.assign(new Error(`${code}: bundled logo is unavailable`), { code });
    vi.doMock("node:fs/promises", () => ({
      readFile: vi.fn().mockRejectedValue(failure),
    }));

    await expect(load().then((route) => route.default())).rejects.toBe(failure);
    expect(ImageResponse).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
});
