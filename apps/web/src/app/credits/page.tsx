import type { Metadata } from "next";
import { heroImages } from "@/lib/hero-images";
import { presentation } from "@/lib/jurisdiction";

export const metadata: Metadata = { title: presentation.creditsTitle };

export default function CreditsPage() {
  return <article className="document-page site-container">
    <h1>A place worth<br />looking closer.</h1>
    <p className="document-lead">{presentation.creditsIntro}</p>
    {presentation.flag && <figure><img src={presentation.flag} alt={presentation.flagAlt} width={1600} height={800} style={{ width: 320, maxWidth: "100%", height: "auto", objectFit: "contain" }} /><figcaption>Unmodified user-supplied reference; public-release approval pending.</figcaption></figure>}
    <div className="photo-credits">{heroImages.map((image) => <figure key={image.id}>
      <img src={image.mobileSrc} alt={image.alt} width={image.width} height={image.height} loading="lazy" />
      <figcaption><h2>{image.place}</h2><p>Photo by <a href={image.photographerUrl} target="_blank" rel="noopener noreferrer">{image.photographer}</a> on <a href={image.sourceUrl} target="_blank" rel="noopener noreferrer">Unsplash</a>.</p></figcaption>
    </figure>)}</div>
    {heroImages.length ? <><p>Photography is used under the <a href="https://unsplash.com/license">Unsplash licence</a>.</p><p>{presentation.creditsNotice}</p></> : <><p>{presentation.creditsNotice}</p><a href="/brand/attribution.json">Read the asset attribution and approval manifest</a></>}
  </article>;
}
