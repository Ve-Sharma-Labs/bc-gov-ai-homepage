"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { MapPin } from "lucide-react";
import { getLocations } from "@/lib/api";
import type { Catalog, Location } from "@/lib/contract";
import { formatDate } from "@/lib/links";
import { OfficialLink } from "./official-link";

export const serviceLabels: Record<string, string> = {
  "icbc-licensing": "ICBC driver licensing",
  "income-assistance": "Income assistance",
  "bc-services-card": "BC Services Card account / ID verification",
  bceid: "BCeID",
};

export function filterLocations(locations: Location[], service: string, municipality: string): Location[] {
  return locations.filter((location) =>
    (!service || (location.services.includes(service) && !location.excludedServices.includes(service))) &&
    (!municipality || location.municipality.toLocaleLowerCase("en-CA") === municipality.toLocaleLowerCase("en-CA")),
  );
}

export function LocationFinder({ catalog }: { catalog: Catalog }) {
  const [service, setService] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [locations, setLocations] = useState(catalog.locations);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const find = async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await getLocations(service, municipality, controller.signal);
      if (!controller.signal.aborted) {
        setLocations(filterLocations(result.locations, service, municipality));
        setExpanded(false);
      }
    } catch {
      if (!controller.signal.aborted) {
        setLocations(filterLocations(catalog.locations, service, municipality));
        setError("The location service is unavailable. These results use the dated catalogue snapshot instead; confirm details before travelling.");
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  return (
    <section className="location-finder" aria-labelledby="locations-heading">
      <h2 id="locations-heading">Find an office that can help</h2>
      <p>Filter the {catalog.locations.length}-office curated snapshot by service, then municipality. This is not a complete or live directory. BC Services Card support here means account setup or ID verification, not photo-card issuance.</p>
      <form className="location-filters" onSubmit={(event) => { event.preventDefault(); void find(); }}>
        <label>Service<select value={service} onChange={(event) => setService(event.target.value)}>
          <option value="">Any supported service</option>
          {Object.entries(serviceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>Municipality<select value={municipality} onChange={(event) => setMunicipality(event.target.value)}>
          <option value="">All in this snapshot</option>
          {[...new Set(catalog.locations.map((location) => location.municipality))].sort().map((place) => <option key={place}>{place}</option>)}
        </select></label>
        <Button className="secondary-button" type="submit" isDisabled={busy}>{busy ? "Finding…" : "Find locations"}</Button>
      </form>
      <p className="location-result-count" role="status">{busy ? "Checking published location records…" : `${locations.length} ${locations.length === 1 ? "location" : "locations"} in these results`}</p>
      {error && <p className="inline-notice" role="status">{error}</p>}
      {!busy && !locations.length && <p className="empty-state">No matching office is verified in this snapshot. Try another filter or use the official Service BC directory. Missing information does not mean a service is unavailable everywhere.</p>}
      <ul className="location-results">
        {(expanded ? locations : locations.slice(0, 3)).map((location) => {
          const source = catalog.sources.find((item) => location.sourceIds.includes(item.id));
          const supported = location.services.filter((item) => !location.excludedServices.includes(item));
          return (
            <li key={location.id} className="location">
              <div className="location-title"><MapPin size={19} aria-hidden="true" /><h3>{location.name}</h3></div>
              <p>{location.address}</p>
              <dl>
                <div><dt>Published hours</dt><dd>{location.hours || "Not provided — check with the office"}</dd></div>
                <div><dt>Verified services</dt><dd>{supported.map((item) => serviceLabels[item] || item).join(", ") || "Not verified"}</dd></div>
                {!!location.excludedServices.length && <div className="exclusions"><dt>Not offered</dt><dd>{location.excludedServices.map((item) => serviceLabels[item] || item).join(", ")}</dd></div>}
                <div><dt>Source checked</dt><dd>{formatDate(location.checkedAt)}</dd></div>
              </dl>
              <p className="muted">Published hours are not live availability. Confirm the service and any appointment requirement before you go.</p>
              {source ? <OfficialLink href={source.url}>Office details and contact</OfficialLink> : <p className="missing-source">Official office source unavailable.</p>}
            </li>
          );
        })}
      </ul>
      {locations.length > 3 && <Button className="text-button" onPress={() => setExpanded(!expanded)}>{expanded ? "Show fewer locations" : `Show all ${locations.length} locations`}</Button>}
    </section>
  );
}
