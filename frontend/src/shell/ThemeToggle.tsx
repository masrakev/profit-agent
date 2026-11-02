import { ROW } from "./sidebar";
import { Tip } from "./Tip";
import { useTheme } from "@/theme/context";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";

/** A sidebar row: the moon in the light theme, the sun in the dark one; a click switches. */
export function ThemeToggle({ collapsed = false }: { collapsed?: boolean }) {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  const label = `${next === "dark" ? "Dark" : "Light"} theme`;
  return (
    <span className="group/tip relative">
      <button
        type="button"
        onClick={toggle}
        aria-label={`Use the ${next} theme`}
        className={cx(ROW, "hover:bg-subtle")}
      >
        <Icon name={theme === "dark" ? "sun" : "moon"} />
        <span className={cx(collapsed && "sr-only")}>{label}</span>
      </button>
      <Tip show={collapsed}>{label}</Tip>
    </span>
  );
}
