import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { OfficialLink } from "@/components/official-link";

export const metadata: Metadata = { title: "Browse official services" };

const services = [
  { name: "Driver licensing and BCID", publisher: "ICBC", description: "Check the official requirements for licensing, identification and office visits.", url: "https://www.icbc.com/driver-licensing" },
  { name: "Rental assistance and housing", publisher: "BC Housing", description: "Explore programmes and check current application guidance directly with BC Housing.", url: "https://www.bchousing.org/housing-assistance" },
  { name: "MSP and PharmaCare", publisher: "Government of B.C.", description: "Find the official starting points for medical and prescription drug coverage.", url: "https://www2.gov.bc.ca/gov/content/health/health-drug-coverage" },
  { name: "Finding primary care", publisher: "HealthLink BC", description: "Learn about the Health Connect Registry and official support routes.", url: "https://www.healthlinkbc.ca/health-connect-registry" },
  { name: "Service BC locations", publisher: "Service BC", description: "Find office details and confirm which services are offered before you go.", url: "https://www2.gov.bc.ca/gov/content/governments/organizational-structure/ministries-organizations/ministries/citizens-services/servicebc" },
  { name: "All government services", publisher: "Government of B.C.", description: "Browse the provincial website for topics outside this pilot’s curated guided plans.", url: "https://www2.gov.bc.ca/gov/content/home" },
];

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
      <Link className="primary-button inline-button" href="/#journeys">Explore guided plans <ArrowUpRight size={17} aria-hidden="true" /></Link>
    </div>
  );
}
