import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent-fill text-on-accent hover:opacity-90 active:opacity-80",
  secondary: "border border-line bg-transparent text-ink hover:bg-subtle",
  ghost: "bg-transparent text-ink-muted hover:bg-subtle hover:text-ink",
  danger: "bg-danger text-on-accent hover:opacity-90 active:opacity-80",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Takes the full width of its container (forms, sheets). */
  block?: boolean;
}

/** Pill buttons: 40 px high, 20 px sides, 15 px medium. Primary is ink on canvas. */
export function Button({
  variant = "primary",
  block = false,
  type = "button",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-full px-5",
        "text-body leading-none font-medium whitespace-nowrap transition-[background-color,opacity,color] duration-150",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        block && "w-full",
        className,
      )}
      {...props}
    />
  );
}
