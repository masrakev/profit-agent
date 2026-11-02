import { NavLink } from "react-router";

import { StoreMenu } from "./StoreMenu";
import { ThemeToggle } from "./ThemeToggle";
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

/** The left rail: the brand, the six destinations, then the theme toggle and the store. */
export function NavRail() {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-y-0 left-0 z-30 flex w-[88px] flex-col items-center gap-7 border-r border-line bg-surface px-3 pt-[26px] pb-6"
    >
      <BrandMark />
      <ul className="flex w-full flex-col gap-2">
        {DESTINATIONS.map((destination) => (
          <li key={destination.to}>
            <NavLink
              to={destination.to}
              end={destination.to === "/"}
              className={({ isActive }) =>
                cx(
                  "flex h-[62px] flex-col items-center justify-center gap-[5px] rounded-destination text-tiny",
                  isActive
                    ? "bg-accent-soft font-semibold text-accent-ink"
                    : "text-ink-muted hover:bg-subtle hover:text-ink",
                )
              }
            >
              <Icon name={destination.icon} />
              {destination.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="mt-auto flex flex-col items-center gap-4">
        <ThemeToggle />
        <StoreMenu />
      </div>
    </nav>
  );
}
