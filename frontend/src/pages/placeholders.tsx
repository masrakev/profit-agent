import { Link } from "react-router";

/** The conversation. Page 1 lays out its frame; the morning brief and answers arrive in page 2. */
export function ChatPage() {
  return (
    <section aria-label="Conversation" className="flex flex-col gap-6">
      <h1 className="sr-only">Chat</h1>
    </section>
  );
}

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
