import { describe, expect, it } from "vitest";
import { alt as openGraphAlt, size as openGraphSize } from "@/app/opengraph-image";
import { siteDescription, siteMetadata, siteTitle, siteUrl, socialImageAlt } from "@/app/site-metadata";
import { alt as twitterAlt, size as twitterSize } from "@/app/twitter-image";

describe("site link metadata", () => {
  it("brands the canonical site as BC.Gov", () => {
    expect(siteMetadata.metadataBase).toEqual(siteUrl);
    expect(siteMetadata.title).toEqual({ default: siteTitle, template: "%s · BC.Gov" });
    expect(siteMetadata.description).toBe(siteDescription);
    expect(siteMetadata.alternates).toEqual({ canonical: "/" });
    expect(siteMetadata.robots).toEqual({ index: false, follow: false });
  });

  it("publishes matching Open Graph and Twitter cards", () => {
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
    expect(openGraphSize).toEqual({ width: 1200, height: 630 });
    expect(twitterSize).toEqual(openGraphSize);
    expect(openGraphAlt).toBe(socialImageAlt);
    expect(twitterAlt).toBe(socialImageAlt);
  });
});
