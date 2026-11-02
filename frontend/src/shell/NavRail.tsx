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

const DESTINATIONS: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Chat", icon: "message-circle" },
  { to: "/today", label: "Today", icon: "sun" },
  { to: "/decisions", label: "Decisions", icon: "circle-check" },
  { to: "/goals", label: "Goals", icon: "flag" },
  { to: "/journal", label: "Journal", icon: "book-open" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

/**
 * The sidebar: expanded, each destination is an icon and its label; collapsed, only the icons,
 * each naming itself on hover. The button at the top switches between the two; collapsed, the
 * brand mark becomes that button on hover.
 */
export function NavRail({ collapsed, onToggle }: SidebarProps) {
  return (
    <nav
      aria-label="Main"
      data-collapsed={collapsed}
      className={cx(
        "fixed inset-y-0 left-0 z-30 flex flex-col border-r border-line bg-surface px-2 pb-2",
        "transition-[width] duration-200 ease-out",
        collapsed ? SIDEBAR.collapsed : SIDEBAR.expanded,
      )}
    >
      <div className="flex h-[52px] shrink-0 items-center justify-between">
        {collapsed ? (
          <span className="group/tip relative">
            <button
              type="button"
              aria-label="Open sidebar"
              aria-expanded={false}
              onClick={onToggle}
              className="group/open flex size-9 cursor-pointer items-center justify-center rounded-[10px] text-ink-muted hover:bg-subtle"
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
            <Link to="/" className="flex size-9 items-center justify-center rounded-[10px]">
              <BrandMark />
              <span className="sr-only">{BRAND.name}: the conversation</span>
            </Link>
            <button
              type="button"
              aria-label="Close sidebar"
              aria-expanded
              onClick={onToggle}
              className="flex size-9 cursor-pointer items-center justify-center rounded-[10px] text-ink-muted hover:bg-subtle hover:text-ink"
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
                cx(ROW, isActive ? "bg-subtle font-medium" : "hover:bg-subtle")
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
        <ThemeToggle collapsed={collapsed} />
        <StoreMenu collapsed={collapsed} />
      </div>
    </nav>
  );
}
