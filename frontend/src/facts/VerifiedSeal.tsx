import { useEffect, useId, useRef, useState } from "react";

import type { Fact } from "./facts";
import { useProof } from "./proofContext";
import { Icon } from "@/ui/Icon";

export const SEAL_TEXT = "Every number here was computed by code from your data.";

/**
 * The "Verified" seal on an answer or card that carries numbers (Task 7, adjustment 3): it opens a
 * short note saying how the numbers were made, with a link to the proof of the card's main number.
 */
export function VerifiedSeal({ fact, title }: { fact: Fact; title?: string }) {
  const [open, setOpen] = useState(false);
  const proof = useProof();
  const root = useRef<HTMLSpanElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const noteId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      toggle.current?.focus();
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
    <span ref={root} className="relative inline-flex">
      <button
        ref={toggle}
        type="button"
        aria-expanded={open}
        aria-controls={noteId}
        onClick={() => {
          setOpen((shown) => !shown);
        }}
        className="inline-flex cursor-pointer items-center gap-1 rounded-full bg-accent-soft px-2 py-[3px] text-caption font-semibold text-accent-ink"
      >
        <Icon name="circle-check" size={12} />
        Verified
      </button>
      <span
        id={noteId}
        hidden={!open}
        className="absolute top-full right-0 z-20 mt-2 w-64 flex-col gap-2 rounded-box border border-line bg-surface p-4 text-small text-ink shadow-float [&:not([hidden])]:flex"
      >
        <span>{SEAL_TEXT}</span>
        <button
          type="button"
          aria-haspopup="dialog"
          onClick={() => {
            setOpen(false);
            proof.open(fact, title);
          }}
          className="cursor-pointer self-start font-semibold text-accent-ink hover:underline"
        >
          See the proof
        </button>
      </span>
    </span>
  );
}
