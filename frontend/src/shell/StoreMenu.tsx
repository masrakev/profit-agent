import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { useSignOut } from "@/auth/session";
import { initials, storeLabel, useStore } from "@/stores/store";

/** The store at the foot of the rail; its menu names the store and signs out. */
export function StoreMenu() {
  const store = useStore();
  const label = storeLabel(store);
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const firstItem = useRef<HTMLButtonElement>(null);
  const signOut = useSignOut();
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    firstItem.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    const onPointer = (event: MouseEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  return (
    <div ref={root} className="relative flex w-16 flex-col items-center">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen((shown) => !shown);
        }}
        className="flex w-16 cursor-pointer flex-col items-center gap-[5px] rounded-destination py-1 hover:bg-subtle"
      >
        <span
          aria-hidden="true"
          className="inline-flex size-8 items-center justify-center rounded-avatar bg-subtle text-label font-semibold text-ink"
        >
          {initials(label)}
        </span>
        <span className="w-16 text-center text-tiny text-ink-muted">
          {label}
          <span aria-hidden="true">&#x2304;</span>
        </span>
      </button>
      <div
        id={menuId}
        role="menu"
        aria-label={label}
        hidden={!open}
        className="absolute bottom-0 left-full z-40 ml-3 w-56 flex-col gap-1 rounded-box border border-line bg-surface p-2 shadow-float [&:not([hidden])]:flex"
      >
        <p className="px-3 py-2 text-label text-ink-muted">{label}</p>
        <button
          ref={firstItem}
          type="button"
          role="menuitem"
          disabled={signOut.isPending}
          onClick={() => {
            signOut.mutate(undefined, {
              onSuccess: () => {
                void navigate("/sign-in", { replace: true });
              },
            });
          }}
          className="cursor-pointer rounded-[8px] px-3 py-2 text-left text-small text-ink hover:bg-subtle"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
