"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="content-container document-page">
      <h1>Something interrupted this page.</h1>
      <p className="document-lead">Try loading it again, or use the official service directory. Any unsaved conversation may need to be restarted.</p>
      <div className="dialog-actions"><button className="primary-button" onClick={reset}>Try again</button><a className="secondary-button" href="/services">Browse services</a></div>
    </div>
  );
}
