import { Link } from "react-router";

/** A destination whose page is not built yet. */
export function PendingPage({ title }: { title: string }) {
  return (
    <section className="flex flex-col gap-3">
      <h1 className="text-title font-semibold text-ink">{title}</h1>
      <p className="text-body text-ink-muted">This page is not built yet.</p>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[460px] flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-title font-semibold text-ink">Nothing here</h1>
      <p className="text-body text-ink-muted">This address does not lead to a page.</p>
      <Link to="/" className="text-body font-semibold text-accent-ink hover:underline">
        Back to your store
      </Link>
    </main>
  );
}
