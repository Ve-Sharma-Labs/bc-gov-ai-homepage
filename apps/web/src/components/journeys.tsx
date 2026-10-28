"use client";

import { Button } from "react-aria-components";
import { ArrowRight, HeartPulse, House, IdCard, MapPin, ShieldPlus, type LucideIcon } from "lucide-react";
import type { Journey, JourneyId } from "@/lib/contract";

export const journeyIcons: Record<JourneyId, LucideIcon> = {
  "licence-renewal": IdCard,
  "road-test-booking": MapPin,
  "rental-assistance": House,
  "health-coverage": ShieldPlus,
  "pharmacare-registration": ShieldPlus,
  "primary-care": HeartPulse,
  "service-bc": MapPin,
};

export function JourneyCards({ journeys, onSelect, compact = false, disabled = false }: {
  journeys: Journey[];
  onSelect: (journey: Journey) => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className={compact ? "journey-list" : "journey-grid"}>
      {journeys.map((journey) => {
        const Icon = journeyIcons[journey.id];
        return (
          <Button key={journey.id} className={`journey-card journey-${journey.id}`} onPress={() => onSelect(journey)} isDisabled={disabled}>
            <span className="journey-icon"><Icon size={compact ? 20 : 26} strokeWidth={1.5} aria-hidden="true" /></span>
            <span className="journey-copy">
              {!compact && <span className="journey-category">{journey.category}</span>}
              <span className="journey-title">{journey.title}</span>
              {!compact && <span className="journey-summary">{journey.summary}</span>}
            </span>
            <ArrowRight className="journey-arrow" size={19} aria-hidden="true" />
          </Button>
        );
      })}
    </div>
  );
}
