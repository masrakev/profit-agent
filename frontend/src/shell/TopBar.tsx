import { AgentStatus } from "./AgentStatus";
import { storeLine, useStore } from "@/stores/store";
import { BrandMark } from "@/ui/BrandMark";
import { Icon } from "@/ui/Icon";

/** The shortcut as the owner's keyboard writes it. */
const SHORTCUT =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";

/**
 * The workspace header: the store on the left (on a phone, the menu and the brand), Ask (from any
 * page) and the agent's status line on the right.
 */
export function TopBar({ onMenu, onAsk }: { onMenu: () => void; onAsk: () => void }) {
  const store = useStore();
  return (
    <header className="flex h-10 items-center justify-between gap-4">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          aria-label="Open the menu"
          onClick={onMenu}
          className="-ml-2 flex size-9 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-subtle hover:text-ink md:hidden"
        >
          <Icon name="panel-left" />
        </button>
        <span className="whitespace-nowrap md:hidden">
          <BrandMark named />
        </span>
        <p className="hidden truncate text-small text-ink-muted md:block">{storeLine(store)}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          onClick={onAsk}
          aria-keyshortcuts="Meta+K Control+K"
          className="hidden h-9 cursor-pointer items-center gap-2 rounded-full border border-line bg-surface pr-2 pl-3 text-small sm:flex text-ink-muted transition-colors duration-150 hover:bg-subtle hover:text-ink"
        >
          <Icon name="message-circle" size={16} />
          <span>Ask</span>
          <kbd className="hidden rounded-sm bg-subtle px-1.5 font-mono text-caption text-ink-muted sm:inline">
            {SHORTCUT}
          </kbd>
        </button>
        <AgentStatus />
      </div>
    </header>
  );
}
