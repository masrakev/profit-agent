import type { ButtonHTMLAttributes } from "react";

import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent-fill text-on-accent hover:brightness-110 active:brightness-95",
  secondary: "bg-subtle text-ink hover:bg-line",
  ghost: "bg-transparent text-accent-ink hover:bg-accent-soft",
  danger: "bg-danger text-on-accent hover:brightness-110 active:brightness-95",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Takes the full width of its container (forms, sheets). */
  block?: boolean;
}

/** The style guide's pill buttons: 42 px high, 20 px sides, 15 px semibold. */
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
      className={cx(
        "inline-flex h-[42px] cursor-pointer items-center justify-center gap-2 rounded-full px-5",
        "text-body leading-none font-semibold whitespace-nowrap transition-[background-color,filter]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        block && "w-full",
        className,
      )}
      {...props}
    />
  );
}
