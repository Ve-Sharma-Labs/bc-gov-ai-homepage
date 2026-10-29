import type {
  ConsentScope,
  ContextCategory,
  DemoPersonaId,
  DemoPersonaSummary,
} from "./contract";

export const SYNTHETIC_CONTEXT_NOTICE =
  "Synthetic demo - no real government records are accessed";

export const contextCategoryDetails: Record<ContextCategory, {
  label: string;
  reason: string;
  scope: ConsentScope;
}> = {
  "identity-residency": {
    label: "Identity and B.C. residency",
    reason: "Confirm the fictional resident and B.C. service pathway.",
    scope: "identity.read",
  },
  "household-dependants": {
    label: "Household and dependants",
    reason: "Tailor questions that depend on the fictional household situation.",
    scope: "household.read",
  },
  "employment-income": {
    label: "Employment and income status",
    reason: "Screen fictional employment and income circumstances against reviewed rules.",
    scope: "employment.read",
  },
  "disability-caregiving": {
    label: "Disability or caregiving circumstances",
    reason: "Prepare the relevant fictional disability or caregiving pathway.",
    scope: "disability-caregiving.read",
  },
  "existing-programs": {
    label: "Existing programs and applications",
    reason: "Avoid repeating fictional program or application information already present.",
    scope: "existing-programs.read",
  },
  "region-preferences": {
    label: "Region and service preferences",
    reason: "Tailor official handoffs and presentation preferences for the fictional scenario.",
    scope: "region-preferences.read",
  },
};

export const contextCategoryByScope = Object.fromEntries(
  Object.entries(contextCategoryDetails).map(([category, details]) => [details.scope, category]),
) as Record<ConsentScope, ContextCategory>;

const personaPlans: Record<DemoPersonaId, {
  purpose: string;
  explanation: string;
  requiredCategories: ContextCategory[];
  proposedCategories: ContextCategory[];
}> = {
  "maya-caregiver": {
    purpose: "Guardianship and caregiving navigation",
    explanation: "Use a minimum set of fictional household, caregiving, existing-authority and service-preference information to prepare a guardianship information pathway.",
    requiredCategories: [
      "household-dependants",
      "disability-caregiving",
      "existing-programs",
    ],
    proposedCategories: [
      "household-dependants",
      "disability-caregiving",
      "existing-programs",
      "region-preferences",
    ],
  },
  "alex-disability-support": {
    purpose: "Disability-support navigation",
    explanation: "Use a minimum set of fictional residency, income, disability, existing-program and service-preference information to screen support pathways.",
    requiredCategories: [
      "identity-residency",
      "employment-income",
      "disability-caregiving",
      "existing-programs",
    ],
    proposedCategories: [
      "identity-residency",
      "employment-income",
      "disability-caregiving",
      "existing-programs",
      "region-preferences",
    ],
  },
  "sam-job-loss": {
    purpose: "Job-loss service navigation",
    explanation: "Use a minimum set of fictional residency, employment and existing-program information to prepare job-loss next steps.",
    requiredCategories: [
      "identity-residency",
      "household-dependants",
      "employment-income",
      "existing-programs",
      "region-preferences",
    ],
    proposedCategories: [
      "identity-residency",
      "household-dependants",
      "employment-income",
      "existing-programs",
      "region-preferences",
    ],
  },
};

export function personaPlan(persona: DemoPersonaSummary) {
  const plan = personaPlans[persona.id];
  const available = new Set(persona.availableCategories);
  return {
    ...plan,
    requiredCategories: plan.requiredCategories.filter((category) => available.has(category)),
    proposedCategories: plan.proposedCategories.filter((category) => available.has(category)),
  };
}

export function categoriesToScopes(categories: Iterable<ContextCategory>): ConsentScope[] {
  return [...new Set([...categories].map((category) => contextCategoryDetails[category].scope))];
}

export function scopesToCategories(scopes: Iterable<ConsentScope>): ContextCategory[] {
  return [...new Set([...scopes].map((scope) => contextCategoryByScope[scope]))];
}

export function humanizeContextIdentifier(value: string): string {
  const words = value
    .replace(/[._-]+/gu, " ")
    .replace(/\b(?:bc)\b/giu, "B.C.")
    .trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Information";
}

export function humanizeContextPurpose(value: string): string {
  return value
    .replace(/^personalize-/u, "")
    .replace(/[._-]+/gu, " ")
    .replace(/\bbc\b/giu, "B.C.");
}
