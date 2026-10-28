import Link from "next/link";

export default function NotFound() {
  return (
    <div className="content-container document-page">
      <h1>Let’s find a better path.</h1>
      <p className="document-lead">That page isn’t part of this pilot. You can start with the assistant or go directly to an official service.</p>
      <div className="dialog-actions"><Link className="primary-button" href="/">Back to the assistant</Link><Link className="secondary-button" href="/services">Browse services</Link></div>
    </div>
  );
}
