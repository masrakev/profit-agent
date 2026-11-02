import { useTheme } from "@/theme/context";
import { Icon } from "@/ui/Icon";

/** The moon in the light theme, the sun in the dark one: a click switches to the other. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Use the ${next} theme`}
      className="inline-flex cursor-pointer rounded-full p-1.5 text-ink-muted hover:bg-subtle hover:text-ink"
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
