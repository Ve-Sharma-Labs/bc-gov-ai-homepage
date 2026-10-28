import { ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { safeOfficialUrl } from "@/lib/links";

export function OfficialLink({ href, children, className = "", newTab = true }: {
  href: string;
  children: ReactNode;
  className?: string;
  newTab?: boolean;
}) {
  const safe = safeOfficialUrl(href);
  if (!safe) return <span className={`unavailable-link ${className}`}>{children} <span>(link unavailable)</span></span>;
  return (
    <a className={`official-link ${className}`} href={safe} target={newTab ? "_blank" : undefined} rel={newTab ? "noopener noreferrer" : undefined}>
      {children}
      <ArrowUpRight size={16} aria-hidden="true" />
      {newTab && <span className="sr-only"> (opens in a new tab)</span>}
    </a>
  );
}
