import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FeatureScenes } from "@/components/feature-scenes";

export const metadata: Metadata = { title: "How it works" };

export default function HowItWorksPage() {
  return <div className="how-page">
    <section className="editorial-opening site-container">
      <h1>A clearer way<br />to your next step.</h1>
      <div className="editorial-intro">
        <p>You don&apos;t need to know which website to visit, or where to begin. Start with what you need. We&apos;ll help you find official information and prepare a plan.</p>
        <p>This pilot brings a few everyday B.C. services into one approachable place. No account to create. No applications submitted for you. Just a helpful place to start.</p>
      </div>
    </section>
    <section className="how-features site-container" aria-labelledby="how-features-heading"><h2 id="how-features-heading">A little help.<br />A lot more clarity.</h2><FeatureScenes /></section>
    <section className="privacy-editorial site-container">
      <div className="privacy-symbol" aria-hidden="true"><span /><span /><span /><span /><span /></div>
      <h2>Your next step.<br />Your choice.</h2>
      <p>Keep personal details out of your questions. Explore a plan without signing in, inspect its sources, and decide when you&apos;re ready to continue.</p>
      <Link className="pill-link" href="/about#privacy">Privacy in this pilot <ArrowRight size={18} /></Link>
    </section>
  </div>;
}
