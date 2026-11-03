import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { TrustMeter } from "@/charts/TrustMeter";
import { useStore } from "@/stores/store";
import { Section } from "@/ui/Section";
import { Skeleton } from "@/ui/Skeleton";
import { StatusPill, type Tone } from "@/ui/StatusPill";

type Trust = Schemas["TrustEntry"];

const ACTIONS: Record<string, string> = {
  pause_campaign: "Pausing a campaign",
  resume_campaign: "Resuming a campaign",
  change_budget: "Changing a daily budget",
  reorder_product: "Reordering a product",
  change_price: "Changing a price",
  new_creative: "Launching a new ad creative",
};

/** SPEC section 7: each autonomy level as the rule it sets, in the owner's words. */
const RULES: Record<number, { tone: Tone; rule: string; words: string }> = {
  1: { tone: "neutral", rule: "Blocked", words: "I only watch: I never do this." },
  2: { tone: "warning", rule: "Needs your approval", words: "I ask you first, every time." },
  3: { tone: "good", rule: "Allowed", words: "I act alone within your caps, and tell you." },
  4: { tone: "good", rule: "Allowed", words: "I manage it within its scope, and tell you." },
};

const CHANNELS: { key: Schemas["AlertChannel"]; label: string }[] = [
  { key: "web", label: "In the app" },
  { key: "email", label: "By email" },
  { key: "whatsapp", label: "On WhatsApp" },
];

/**
 * Settings, in the same row language as the rest: for each kind of action, the rule it follows
 * (allowed, needs your approval, blocked) and how far I have earned the right to do it alone;
 * then where I reach you. Read here; changing them comes with the full settings page.
 */
export function SettingsPage() {
  const api = useApi();
  const { storeId } = useStore();
  const path = { params: { path: { store_id: storeId } } };
  const settings = useQuery({
    queryKey: ["settings", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/settings", path)),
  });
  const trust = useQuery({
    queryKey: ["trust", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/trust", path)),
  });

  const levels = settings.data?.autonomy ?? {};
  const entries = new Map<string, Trust>((trust.data ?? []).map((t) => [t.action_type, t]));
  const kinds = [...new Set([...Object.keys(ACTIONS), ...Object.keys(levels), ...entries.keys()])];

  return (
    <section aria-labelledby="settings-title" className="flex flex-col gap-12">
      <header className="flex flex-col gap-2">
        <h1 id="settings-title" className="text-title font-semibold text-ink">
          Settings
        </h1>
        <p className="text-body text-ink-muted">
          What I may do on your store, and where I reach you.
        </p>
      </header>
      {(settings.isPending || trust.isPending) && <Skeleton rows={3} />}
      {settings.isError && (
        <p className="text-body text-ink-muted">Your settings could not be loaded.</p>
      )}
      {settings.data && (
        <>
          <Section title="What I may do">
            <ul className="flex flex-col" data-stagger>
              {kinds.map((kind) => {
                const entry = entries.get(kind);
                const level = levels[kind] ?? entry?.level;
                const rule = level === undefined ? undefined : RULES[level];
                return (
                  <li
                    key={kind}
                    aria-label={ACTIONS[kind] ?? kind}
                    className="flex flex-col gap-1.5 border-b border-line py-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="text-body font-medium text-ink">
                        {ACTIONS[kind] ?? kind}
                      </span>
                      {rule && <StatusPill tone={rule.tone}>{rule.rule}</StatusPill>}
                    </div>
                    <span className="text-small text-ink-muted">
                      {rule?.words ?? "Not set: I ask you first."}
                    </span>
                    {entry?.progress && (
                      <span className="flex flex-wrap items-center gap-2.5 text-label text-ink-muted">
                        <TrustMeter
                          confirmations={entry.confirmations}
                          threshold={entry.threshold}
                        />
                        {entry.progress}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </Section>
          <Section title="History">
            <p className="flex items-center justify-between gap-3 border-b border-line py-4">
              <span className="text-body text-ink">
                Everything that happened: what I found, what you decided, what changed.
              </span>
              <Link
                to="/journal"
                className="shrink-0 rounded-md text-small font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink-muted"
              >
                Open the journal
              </Link>
            </p>
          </Section>
          <Section title="Where I reach you">
            <ul className="flex flex-col">
              {CHANNELS.map((channel) => {
                const on = settings.data.alert_channels.includes(channel.key);
                return (
                  <li
                    key={channel.key}
                    className="flex items-center justify-between gap-3 border-b border-line py-4"
                  >
                    <span className="text-body text-ink">{channel.label}</span>
                    <StatusPill tone={on ? "good" : "neutral"}>{on ? "On" : "Off"}</StatusPill>
                  </li>
                );
              })}
            </ul>
          </Section>
        </>
      )}
    </section>
  );
}
