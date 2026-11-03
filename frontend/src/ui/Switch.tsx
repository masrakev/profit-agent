import { cx } from "./cx";

/** An on/off setting: a switch named by its row's label, saved as soon as it is flipped. */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => {
        onChange(!checked);
      }}
      className={cx(
        "relative inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-accent-fill" : "bg-line",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "inline-block size-5 rounded-full bg-surface shadow-float transition-transform duration-150",
          checked ? "translate-x-4.5" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
