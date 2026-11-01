const officialHosts = [
  "gov.bc.ca",
  "icbc.com",
  "bchousing.org",
  "healthlinkbc.ca",
  "workbc.ca",
  "bclaws.gov.bc.ca",
  "canada.ca",
  "trustee.bc.ca",
];

export function safeOfficialUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2048 || /[\u0000-\u0020\\]/u.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
    if (!officialHosts.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`))) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function sourceDomain(value: string): string {
  const safe = safeOfficialUrl(value);
  return safe ? new URL(safe).hostname.replace(/^www\./u, "") : "Destination unavailable";
}

export function formatDate(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not provided";
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: value.includes("T") ? "America/Vancouver" : "UTC",
  }).format(new Date(value));
}

export function sourceNeedsReview(source: { status: string; checkedAt: string | null }, now = Date.now()): boolean {
  if (source.status !== "available" || !source.checkedAt) return true;
  const age = now - Date.parse(source.checkedAt);
  return !Number.isFinite(age) || age > 7 * 24 * 60 * 60 * 1000;
}
