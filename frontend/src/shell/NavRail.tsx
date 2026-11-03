import { Link, NavLink } from "react-router";

import { ROW, SIDEBAR } from "./sidebar";
import { StoreMenu } from "./StoreMenu";
import { ThemeToggle } from "./ThemeToggle";
import { Tip } from "./Tip";
import { BRAND } from "@/brand";
import { BrandMark } from "@/ui/BrandMark";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";
import type { IconName } from "@/ui/icons";

/** Four places: the day, the questions, the decisions, the goals. Settings sits at the foot. */
const DESTINATIONS: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Home", icon: "sun" },
  { to: "/chat", label: "Conversations", icon: "message-circle" },
  { to: "/decisions", label: "Decisions", icon: "circle-check" },
  { to: "/goals", label: "Goals", icon: "flag" },
];
const SETTINGS = { to: "/settings", label: "Settings", icon: "settings" } as const;

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  /** On a phone the rail is a drawer: open, or off screen. */
  drawer?: boolean;
  onClose?: () => void;
}

/**
 * The sidebar: expanded, each destination is an icon and its label; collapsed, only the icons,
 * each naming itself on hover. The button at the top switches between the two; collapsed, the
 * brand mark becomes that button on hover.
 */
export function NavRail({ collapsed: chosen, onToggle, drawer = false, onClose }: SidebarProps) {
  // A drawer is always expanded.
  const collapsed = chosen && !drawer;
  return (
    <nav
      aria-label="Main"
      data-collapsed={collapsed}
      className={cx(
        "fixed inset-y-0 left-0 z-30 flex flex-col border-r border-line bg-canvas px-2 pb-2",
        "transition-[width,translate] duration-200 ease-out",
        collapsed ? SIDEBAR.collapsed : SIDEBAR.expanded,
        drawer ? "max-md:translate-x-0 max-md:shadow-float" : "max-md:-translate-x-full",
      )}
    >
      <div className="flex h-[52px] shrink-0 items-center justify-between pl-1">
        {drawer ? (
          <>
            <BrandMark named />
            <button
              type="button"
              aria-label="Close the menu"
              onClick={onClose}
              className="flex size-9 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-subtle hover:text-ink"
            >
              <Icon name="x" />
            </button>
          </>
        ) : collapsed ? (
          <span className="group/tip relative">
            <button
              type="button"
              aria-label="Open sidebar"
              aria-expanded={false}
              onClick={onToggle}
              className="group/open flex size-9 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-subtle"
            >
              <span className="group-hover/open:hidden group-focus-visible/open:hidden">
                <BrandMark />
              </span>
              <span className="hidden group-hover/open:inline-flex group-focus-visible/open:inline-flex">
                <Icon name="panel-left" />
              </span>
            </button>
            <Tip show>Open sidebar</Tip>
          </span>
        ) : (
          <>
            <Link
              to="/"
              aria-label={`${BRAND.name}: the conversation`}
              className="flex h-9 items-center rounded-md"
            >
              <BrandMark named />
            </Link>
            <button
              type="button"
              aria-label="Close sidebar"
              aria-expanded
              onClick={onToggle}
              className="flex size-9 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-subtle hover:text-ink"
            >
              <Icon name="panel-left" />
            </button>
          </>
        )}
      </div>
      <ul className="flex flex-col gap-px">
        {DESTINATIONS.map((destination) => (
          <li key={destination.to} className="group/tip relative">
            <NavLink
              to={destination.to}
              end={destination.to === "/"}
              className={({ isActive }) =>
                cx(ROW, isActive ? "bg-subtle font-medium text-ink" : "hover:bg-subtle")
              }
            >
              <Icon name={destination.icon} />
              <span className={cx(collapsed && "sr-only")}>{destination.label}</span>
            </NavLink>
            <Tip show={collapsed}>{destination.label}</Tip>
          </li>
        ))}
      </ul>
      <div className="mt-auto flex flex-col gap-px">
        <span className="group/tip relative">
          <NavLink
            to={SETTINGS.to}
            className={({ isActive }) =>
              cx(ROW, isActive ? "bg-subtle font-medium text-ink" : "hover:bg-subtle")
            }
          >
            <Icon name={SETTINGS.icon} />
            <span className={cx(collapsed && "sr-only")}>{SETTINGS.label}</span>
          </NavLink>
          <Tip show={collapsed}>{SETTINGS.label}</Tip>
        </span>
        <ThemeToggle collapsed={collapsed} />
        <StoreMenu collapsed={collapsed} />
      </div>
    </nav>
  );
}
