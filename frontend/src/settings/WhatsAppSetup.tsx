import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { ApiError, unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { useWhatsAppNumber } from "./whatsapp";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { StatusPill } from "@/ui/StatusPill";

type Settings = Schemas["StoreSettings-Output"];

const PROBLEMS: Record<string, string> = {
  whatsapp_unavailable: "WhatsApp is not set up on this server yet.",
  whatsapp_failed: "The code could not be sent. Try again.",
  too_many_codes: "Three codes an hour at most: try again later.",
  invalid_code: "That code does not match.",
  expired_code: "That code has expired: send a new one.",
  too_many_attempts: "Too many attempts: send a new code.",
};
const NUMBER_FORMAT = "Write the number with its country code, for example +33612345678.";

function problemOf(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Try again.";
  const known = error.code ? PROBLEMS[error.code] : undefined;
  if (known) return known;
  return error.status === 422 ? NUMBER_FORMAT : "Something went wrong. Try again.";
}

/** The number as typed, as the API takes it: "+33 6 12-34" is "+33612 34". */
const typed = (text: string) => text.replace(/[\s().-]/g, "");

/**
 * WhatsApp, set up in place: the number (with its country code), a code sent to it on WhatsApp,
 * the code typed here. Once verified, WhatsApp joins the channels; the number can be changed,
 * which starts over.
 */
export function WhatsAppSetup({ settings }: { settings: Settings }) {
  const api = useApi();
  const queries = useQueryClient();
  const { storeId } = useStore();
  const path = { params: { path: { store_id: storeId } } };
  const number = useWhatsAppNumber();
  const [phone, setPhone] = useState(settings.whatsapp_number ?? "");
  const [code, setCode] = useState("");
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const phoneId = useId();
  const codeId = useId();

  const saveSettings = async (next: Settings) => {
    const saved = await unwrap(
      api.PUT("/api/v1/stores/{store_id}/settings", { ...path, body: next }),
    );
    queries.setQueryData(["settings", storeId], saved);
    return saved;
  };
  const latest = () => queries.getQueryData<Settings>(["settings", storeId]) ?? settings;

  const send = useMutation({
    mutationFn: async (e164: string) => {
      if (e164 !== latest().whatsapp_number) {
        await saveSettings({ ...latest(), whatsapp_number: e164 });
      }
      return unwrap(api.POST("/api/v1/stores/{store_id}/whatsapp/verification", path));
    },
    onMutate: () => {
      setProblem(null);
    },
    onSuccess: async () => {
      setEditing(false);
      setCode("");
      await queries.invalidateQueries({ queryKey: ["whatsapp", storeId] });
    },
    onError: (error) => {
      setProblem(problemOf(error));
    },
  });
  const confirm = useMutation({
    mutationFn: async () => {
      const state = await unwrap(
        api.POST("/api/v1/stores/{store_id}/whatsapp/verification/confirm", {
          ...path,
          body: { code },
        }),
      );
      const current = latest();
      if (!current.alert_channels.includes("whatsapp")) {
        await saveSettings({ ...current, alert_channels: [...current.alert_channels, "whatsapp"] });
      }
      return state;
    },
    onMutate: () => {
      setProblem(null);
    },
    onSuccess: (state) => {
      queries.setQueryData(["whatsapp", storeId], state);
      setCode("");
    },
    onError: (error) => {
      setProblem(problemOf(error));
    },
  });

  const state = number.data;
  const busy = send.isPending || confirm.isPending;
  const waiting = !editing && state?.code_expires_at != null && !state.verified;

  return (
    <li className="flex flex-col gap-3 border-b border-line py-4">
      {state?.verified && !editing ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-3">
            <span className="font-mono text-small text-ink">{state.number}</span>
            <StatusPill tone="good">Verified</StatusPill>
          </span>
          <Button
            variant="ghost"
            className="h-9 px-3 text-small"
            onClick={() => {
              setEditing(true);
            }}
          >
            Change number
          </Button>
        </div>
      ) : waiting ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            confirm.mutate();
          }}
        >
          <label htmlFor={codeId} className="text-small text-ink-muted">
            The code I sent on WhatsApp to {state.number}
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id={codeId}
              value={code}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="6 digits"
              onChange={(event) => {
                setCode(event.target.value.replace(/\D/g, ""));
              }}
              className="h-9 w-32 rounded-md border border-line bg-surface px-2.5 font-mono text-small tracking-widest text-ink placeholder:font-sans placeholder:tracking-normal placeholder:text-ink-muted"
            />
            <Button
              type="submit"
              className="h-9 px-4 text-small"
              disabled={busy || code.length !== 6}
            >
              Confirm
            </Button>
            <Button
              variant="ghost"
              className="h-9 px-3 text-small"
              disabled={busy}
              onClick={() => {
                send.mutate(state.number ?? typed(phone));
              }}
            >
              Send a new code
            </Button>
            <Button
              variant="ghost"
              className="h-9 px-3 text-small"
              disabled={busy}
              onClick={() => {
                setEditing(true);
              }}
            >
              Change number
            </Button>
          </div>
        </form>
      ) : (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            send.mutate(typed(phone));
          }}
        >
          <label htmlFor={phoneId} className="text-small text-ink-muted">
            Your WhatsApp number, with its country code
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id={phoneId}
              type="tel"
              value={phone}
              autoComplete="tel"
              placeholder="+33 6 12 34 56 78"
              onChange={(event) => {
                setPhone(event.target.value);
              }}
              className="h-9 min-w-0 flex-1 basis-48 rounded-md border border-line bg-surface px-2.5 text-small text-ink placeholder:text-ink-muted"
            />
            <Button
              type="submit"
              className="h-9 px-4 text-small"
              disabled={busy || !/^\+[1-9][0-9]{6,14}$/.test(typed(phone))}
            >
              Send me a code
            </Button>
            {editing && (
              <Button
                variant="ghost"
                className="h-9 px-3 text-small"
                onClick={() => {
                  setEditing(false);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      )}
      <p role="status" className="min-h-5 text-small text-danger-ink">
        {problem}
      </p>
    </li>
  );
}
