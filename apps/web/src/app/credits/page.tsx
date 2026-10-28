import type { Metadata } from "next";
import { heroImages } from "@/lib/hero-images";

export const metadata: Metadata = { title: "Photo credits" };

export default function CreditsPage() {
  return <article className="document-page site-container">
    <h1>A place worth<br />looking closer.</h1>
    <p className="document-lead">British Columbia, photographed by the Unsplash community. These images illustrate places, not endorsements of this pilot.</p>
    <div className="photo-credits">{heroImages.map((image) => <figure key={image.id}>
      <img src={image.mobileSrc} alt={image.alt} width={image.width} height={image.height} loading="lazy" />
      <figcaption><h2>{image.place}</h2><p>Photo by <a href={image.photographerUrl} target="_blank" rel="noopener noreferrer">{image.photographer}</a> on <a href={image.sourceUrl} target="_blank" rel="noopener noreferrer">Unsplash</a>.</p></figcaption>
    </figure>)}</div>
    <p>Photography is used under the <a href="https://unsplash.com/license">Unsplash licence</a>. BC Sans and the display typeface are self-hosted with their open licence notices. Visual identity and public-release approval remain separate.</p>
  </article>;
}
