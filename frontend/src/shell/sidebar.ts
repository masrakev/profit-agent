import { useCallback, useState } from "react";

import { safeStorage } from "@/theme/theme";

/**
 * The sidebar is expanded (icons and labels) or collapsed (icons only); the owner's choice is
 * remembered, and still holds for the visit when storage is refused.
 */
export const SIDEBAR_STORAGE_KEY = "profit-agent.sidebar";

export function readCollapsed(storage: Pick<Storage, "getItem"> | null): boolean {
  try {
    return storage?.getItem(SIDEBAR_STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

export function writeCollapsed(storage: Pick<Storage, "setItem"> | null, collapsed: boolean) {
  try {
    storage?.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "collapsed" : "expanded");
  } catch {
    // Storage refused: the choice holds until the page is reloaded.
  }
}

export function useSidebar(): { collapsed: boolean; toggle: () => void } {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(safeStorage()));
  const toggle = useCallback(() => {
    writeCollapsed(safeStorage(), !collapsed);
    setCollapsed(!collapsed);
  }, [collapsed]);
  return { collapsed, toggle };
}

/** Widths of the sidebar, and of the space the pages leave for it. */
export const SIDEBAR = {
  expanded: "w-[260px]",
  collapsed: "w-[52px]",
  besideExpanded: "md:pl-[300px]",
  besideCollapsed: "md:pl-[92px]",
};

/**
 * A row of the sidebar: an icon, then its label. The icon sits at the same place in both states
 * (8 px into a 36 px row), so collapsing only hides the labels; nothing moves.
 */
export const ROW =
  "flex h-9 w-full cursor-pointer items-center gap-2.5 overflow-hidden rounded-md px-2 " +
  "text-left text-nav whitespace-nowrap text-ink-muted transition-colors duration-150 hover:text-ink";
