import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { OfficialLink } from "@/components/official-link";
import { jurisdiction, presentation } from "@/lib/jurisdiction";

export const metadata: Metadata = { title: "Browse official services" };

const services = presentation.services;

export default function ServicesPage() {
  return (
    <div className="content-container document-page">
      <Link className="back-link" href="/"><ArrowLeft size={15} aria-hidden="true" />Back to the assistant</Link>
      <h1>The official service.<br /><span>A direct way there.</span></h1>
      <p className="document-lead">You don’t need an AI answer to find your way. These links take you straight to the organisations responsible for the services.</p>
      <p className="inline-notice">Links open in a new tab. Check current requirements on the destination site. This directory remains available without JavaScript or an AI connection.</p>
      <div className="service-directory">
        {services.map((service) => (
          <section key={service.url}>
            <span className="directory-publisher">{service.publisher}</span>
            <h2><OfficialLink href={service.url}>{service.name}</OfficialLink></h2>
            <p>{service.description}</p>
          </section>
        ))}
      </div>
      {jurisdiction.features.guidedJourneys ? <Link className="primary-button inline-button" href="/#journeys">Explore guided plans <ArrowUpRight size={17} aria-hidden="true" /></Link>
        : <p className="inline-notice">{presentation.emptyJourneys}</p>}
    </div>
  );
}
