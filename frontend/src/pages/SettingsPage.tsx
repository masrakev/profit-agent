import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { ApiError, unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { TrustMeter } from "@/charts/TrustMeter";
import { useStore } from "@/stores/store";
import { cx } from "@/ui/cx";
import { Section } from "@/ui/Section";
import { Skeleton } from "@/ui/Skeleton";
import { Switch } from "@/ui/Switch";

type Settings = Schemas["StoreSettings-Output"];
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
const RULES: Record<number, { rule: string; words: string }> = {
  1: { rule: "Blocked", words: "I only watch: I never do this." },
  2: { rule: "Needs your approval", words: "I ask you first, every time." },
  3: { rule: "Allowed", words: "I act alone within your caps, and tell you." },
  4: { rule: "Allowed in its scope", words: "I manage it within its scope, and tell you." },
};

type Saving = "idle" | "saving" | "saved" | "failed";

/** "08:00:00" as a time field shows it: "08:00". */
const clock = (at: string | undefined) => (at ?? "").slice(0, 5);

/**
 * Settings, changed in place: each change is saved at once and said so. For each kind of action,
 * the rule it follows; acting alone is offered only once I have earned it (the trust ledger
 * proposes it) or you allowed it before. Then when and where I write to you, and the brake that
 * stops every action.
 */
export function SettingsPage() {
  const api = useApi();
  const queries = useQueryClient();
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
  const brake = useQuery({
    queryKey: ["kill-switch", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/kill-switch", path)),
  });
  const [saving, setSaving] = useState<Saving>("idle");
  const [problem, setProblem] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (next: Settings) =>
      unwrap(
        api.PUT("/api/v1/stores/{store_id}/settings", {
          ...path,
          body: next,
        }),
      ),
    onMutate: () => {
      setSaving("saving");
      setProblem(null);
    },
    onSuccess: (saved) => {
      queries.setQueryData(["settings", storeId], saved);
      void queries.invalidateQueries({ queryKey: ["trust", storeId] });
      setSaving("saved");
    },
    onError: (error) => {
      setSaving("failed");
      setProblem(
        error instanceof ApiError && error.status === 422
          ? "That value is not accepted: it was not saved."
          : "Your change could not be saved. Try again.",
      );
    },
  });
  const stop = useMutation({
    mutationFn: (enabled: boolean) =>
      unwrap(
        api.PUT("/api/v1/stores/{store_id}/kill-switch", {
          ...path,
          body: { enabled, reason: enabled ? "stopped from the settings" : null },
        }),
      ),
    onMutate: () => {
      setSaving("saving");
      setProblem(null);
    },
    onSuccess: (state) => {
      queries.setQueryData(["kill-switch", storeId], state);
      setSaving("saved");
    },
    onError: () => {
      setSaving("failed");
      setProblem("The brake could not be changed. Try again.");
    },
  });

  const current = settings.data;
  const change = (patch: Partial<Settings>) => {
    if (current) save.mutate({ ...current, ...patch });
  };
  const levels = current?.autonomy ?? {};
  const entries = new Map<string, Trust>((trust.data ?? []).map((t) => [t.action_type, t]));
  const kinds = [...new Set([...Object.keys(ACTIONS), ...Object.keys(levels), ...entries.keys()])];

  return (
    <section aria-labelledby="settings-title" className="flex flex-col gap-12">
      <header className="flex flex-col gap-2">
        <h1 id="settings-title" className="text-title font-semibold text-ink">
          Settings
        </h1>
        <p className="text-body text-ink-muted">
          What I may do on your store, when and where I reach you. Each change is saved at once.
        </p>
        <p
          role="status"
          className={cx(
            "min-h-5 text-small",
            saving === "failed" ? "text-danger-ink" : "text-ink-muted",
          )}
        >
          {saving === "saving" && "Saving…"}
          {saving === "saved" && "Saved."}
          {saving === "failed" && problem}
        </p>
      </header>
      {(settings.isPending || trust.isPending) && <Skeleton rows={3} />}
      {settings.isError && (
        <p className="text-body text-ink-muted">Your settings could not be loaded.</p>
      )}
      {current && (
        <>
          <Section title="What I may do">
            <ul className="flex flex-col" data-stagger>
              {kinds.map((kind) => {
                const entry = entries.get(kind);
                const level = levels[kind] ?? entry?.level ?? 2;
                // Acting alone is earned: offered once the ledger proposes it, or already set.
                const offered = [1, 2, 3, 4].filter(
                  (l) => l <= 2 || l === level || (entry?.proposed_level ?? 0) >= l,
                );
                return (
                  <li
                    key={kind}
                    aria-label={ACTIONS[kind] ?? kind}
                    className="flex flex-col gap-2.5 border-b border-line py-4"
                  >
                    <div className="flex flex-col gap-1">
                      <span className="text-body font-medium text-ink">
                        {ACTIONS[kind] ?? kind}
                      </span>
                      <span className="text-small text-ink-muted">{RULES[level]?.words}</span>
                    </div>
                    <Choice
                      label={`Rule for ${(ACTIONS[kind] ?? kind).toLowerCase()}`}
                      options={offered.map((l) => ({
                        value: String(l),
                        text: RULES[l]?.rule ?? String(l),
                      }))}
                      value={String(level)}
                      disabled={save.isPending}
                      onChange={(next) => {
                        change({
                          autonomy: { ...levels, [kind]: Number(next) as 1 | 2 | 3 | 4 },
                        });
                      }}
                    />
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
          <Section title="When I write to you">
            <ul className="flex flex-col">
              <Row
                label="Morning brief"
                hint="Your day: what changed, what needs you."
                control={
                  <span className="flex items-center gap-3">
                    <TimeField
                      label="Morning brief at"
                      value={clock(current.daily_brief.at)}
                      disabled={!current.daily_brief.enabled}
                      onSave={(at) => {
                        change({ daily_brief: { ...current.daily_brief, at } });
                      }}
                    />
                    <Switch
                      label="Morning brief"
                      checked={current.daily_brief.enabled}
                      onChange={(enabled) => {
                        change({ daily_brief: { ...current.daily_brief, enabled } });
                      }}
                    />
                  </span>
                }
              />
              <Row
                label="Weekly report"
                hint="Monday morning: the week that ended."
                control={
                  <Switch
                    label="Weekly report"
                    checked={current.weekly_report.enabled}
                    onChange={(enabled) => {
                      change({ weekly_report: { ...current.weekly_report, enabled } });
                    }}
                  />
                }
              />
              <Row
                label="Quiet hours"
                hint="Only critical alerts reach you between these times."
                control={
                  <span className="flex items-center gap-2 text-small text-ink-muted">
                    <TimeField
                      label="Quiet from"
                      value={clock(current.quiet_hours.start)}
                      onSave={(start) => {
                        change({ quiet_hours: { ...current.quiet_hours, start } });
                      }}
                    />
                    to
                    <TimeField
                      label="Quiet until"
                      value={clock(current.quiet_hours.end)}
                      onSave={(end) => {
                        change({ quiet_hours: { ...current.quiet_hours, end } });
                      }}
                    />
                  </span>
                }
              />
              <Row
                label="Alerts a day"
                hint="Beyond them, the rest waits for the next brief. Critical ones always come."
                control={
                  <TextField
                    label="Alerts a day"
                    type="number"
                    value={String(current.alert_budget_per_day)}
                    className="w-20 text-right tabular-nums"
                    onSave={(text) => {
                      if (/^\d+$/.test(text)) change({ alert_budget_per_day: Number(text) });
                    }}
                  />
                }
              />
            </ul>
          </Section>
          <Section title="Where I reach you">
            <ul className="flex flex-col">
              <Row
                label="In the app"
                hint="Always: everything is here."
                control={<span className="text-small text-ink-muted">Always on</span>}
              />
              <Row
                label="By email"
                hint={
                  current.notification_email
                    ? "Alerts and briefs, to the address below."
                    : "Add an address below to receive them."
                }
                control={
                  <Switch
                    label="By email"
                    checked={
                      current.alert_channels.includes("email") && !!current.notification_email
                    }
                    disabled={!current.notification_email}
                    onChange={(on) => {
                      change({ alert_channels: toggled(current.alert_channels, "email", on) });
                    }}
                  />
                }
              />
              <li className="border-b border-line py-4">
                <TextField
                  label="Email address"
                  type="email"
                  visibleLabel
                  value={current.notification_email ?? ""}
                  placeholder="you@yourstore.com"
                  className="w-full"
                  onSave={(text) => {
                    change({ notification_email: text.trim() || null });
                  }}
                />
              </li>
              <Row
                label="On WhatsApp"
                hint={
                  current.whatsapp_number
                    ? "Alerts and approvals, on your verified number."
                    : "Needs your number, verified: not set up yet."
                }
                control={
                  <Switch
                    label="On WhatsApp"
                    checked={
                      current.alert_channels.includes("whatsapp") && !!current.whatsapp_number
                    }
                    disabled={!current.whatsapp_number}
                    onChange={(on) => {
                      change({ alert_channels: toggled(current.alert_channels, "whatsapp", on) });
                    }}
                  />
                }
              />
            </ul>
          </Section>
          <Section title="Safety">
            <ul className="flex flex-col">
              <Row
                label="Stop every action"
                hint={
                  brake.data?.enabled
                    ? "On: nothing I do runs, even what you approved, until you turn it off."
                    : "A brake: while it is on, nothing I do runs, even what you approved."
                }
                control={
                  <Switch
                    label="Stop every action"
                    checked={brake.data?.enabled ?? false}
                    disabled={!brake.data || stop.isPending}
                    onChange={(enabled) => {
                      stop.mutate(enabled);
                    }}
                  />
                }
              />
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
        </>
      )}
    </section>
  );
}

function toggled(
  channels: Settings["alert_channels"],
  channel: Settings["alert_channels"][number],
  on: boolean,
): Settings["alert_channels"] {
  const rest = channels.filter((c) => c !== channel);
  return on ? [...rest, channel] : rest;
}

/** A settings row: what it is and what it does, its control on the right. */
function Row({ label, hint, control }: { label: string; hint: string; control: ReactNode }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-b border-line py-4">
      <span className="flex min-w-0 grow basis-48 flex-col gap-1">
        <span className="text-body text-ink">{label}</span>
        <span className="text-small text-ink-muted">{hint}</span>
      </span>
      {control}
    </li>
  );
}

/** One rule out of a few, as a row of pills (a radio group). */
function Choice({
  label,
  options,
  value,
  disabled,
  onChange,
}: {
  label: string;
  options: { value: string; text: string }[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const name = useId();
  return (
    <fieldset className="flex flex-wrap gap-1.5" disabled={disabled}>
      <legend className="sr-only">{label}</legend>
      {options.map((o) => (
        <label
          key={o.value}
          className={cx(
            "inline-flex h-8 cursor-pointer items-center rounded-full border px-3 text-small transition-colors duration-150 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent-mark",
            o.value === value
              ? "border-transparent bg-subtle font-medium text-ink"
              : "border-line text-ink-muted hover:text-ink",
          )}
        >
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={o.value === value}
            onChange={() => {
              onChange(o.value);
            }}
            className="sr-only"
          />
          {o.text}
        </label>
      ))}
    </fieldset>
  );
}

const FIELD =
  "h-9 rounded-md border border-line bg-surface px-2.5 text-small text-ink placeholder:text-ink-muted disabled:opacity-50";

/** A time, saved when the field is left with a new value. */
function TimeField({
  label,
  value,
  disabled = false,
  onSave,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  onSave: (at: string) => void;
}) {
  return (
    <TextField
      label={label}
      type="time"
      value={value}
      disabled={disabled}
      className="w-36 font-mono"
      onSave={(at) => {
        if (at) onSave(at);
      }}
    />
  );
}

/** A text, a number or a time: saved when the field is left (or Enter) with a new value. */
function TextField({
  label,
  type,
  value,
  placeholder,
  disabled = false,
  visibleLabel = false,
  className,
  onSave,
}: {
  label: string;
  type: "text" | "email" | "number" | "time";
  value: string;
  placeholder?: string;
  disabled?: boolean;
  visibleLabel?: boolean;
  className?: string;
  onSave: (value: string) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  const [shown, setShown] = useState(value);
  // A value saved elsewhere replaces what the field shows.
  if (value !== shown) {
    setShown(value);
    setDraft(value);
  }
  const commit = () => {
    if (draft !== value) onSave(draft);
  };
  return (
    <span className={cx("flex flex-col gap-1.5", visibleLabel && "w-full")}>
      <label htmlFor={id} className={visibleLabel ? "text-small text-ink-muted" : "sr-only"}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        min={type === "number" ? 0 : undefined}
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
        className={cx(FIELD, className)}
      />
    </span>
  );
}
