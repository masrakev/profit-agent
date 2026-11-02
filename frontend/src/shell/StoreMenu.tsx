import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { useSignOut } from "@/auth/session";
import { ROW } from "./sidebar";
import { Tip } from "./Tip";
import { initials, storeLabel, useStore } from "@/stores/store";
import { cx } from "@/ui/cx";

/** The store at the foot of the sidebar, as a row; its menu signs out. */
export function StoreMenu({ collapsed = false }: { collapsed?: boolean }) {
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
    <div ref={root} className="group/tip relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen((shown) => !shown);
        }}
        className={cx(ROW, "h-11 hover:bg-subtle", open && "bg-subtle")}
      >
        <span
          aria-hidden="true"
          className="-mx-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-subtle text-caption font-semibold text-ink"
        >
          {initials(label)}
        </span>
        <span className={cx("min-w-0 flex-1 truncate", collapsed && "sr-only")}>{label}</span>
      </button>
      <Tip show={collapsed && !open}>{label}</Tip>
      <div
        id={menuId}
        role="menu"
        aria-label={label}
        hidden={!open}
        className={cx(
          "absolute z-40 flex-col gap-1 rounded-box border border-line bg-surface p-2 shadow-float [&:not([hidden])]:flex",
          collapsed ? "bottom-0 left-full ml-2 w-56" : "bottom-full left-0 mb-1 w-full",
        )}
      >
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
