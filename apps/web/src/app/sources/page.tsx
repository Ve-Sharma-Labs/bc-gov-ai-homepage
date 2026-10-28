import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { SourceDirectory } from "@/components/source-directory";

export const metadata: Metadata = { title: "Our sources" };

export default function SourcesPage() {
  return (
    <div className="content-container document-page">
      <Link className="back-link" href="/"><ArrowLeft size={15} aria-hidden="true" />Back to the assistant</Link>
      <h1>Good guidance starts<br /><span>with good sources.</span></h1>
      <p className="document-lead">See where the pilot’s information comes from, when it was checked, and where there are limits. Deferred and restricted sources stay visible—not quietly filled in.</p>
      <p className="inline-notice">“Available snapshot” does not mean live verification or a complete AI knowledge index. Fees, eligibility, office services and other changing details must be confirmed with the responsible organisation.</p>
      <SourceDirectory />
    </div>
  );
}
