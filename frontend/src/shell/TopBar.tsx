import { AgentStatus } from "./AgentStatus";
import { storeLine, useStore } from "@/stores/store";
import { BrandMark } from "@/ui/BrandMark";
import { Icon } from "@/ui/Icon";

/**
 * The workspace header: the store on the left (on a phone, the menu and the brand), the agent's
 * status line on the right.
 */
export function TopBar({ onMenu }: { onMenu: () => void }) {
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
        <span className="md:hidden">
          <BrandMark named />
        </span>
        <p className="hidden truncate text-small text-ink-muted md:block">{storeLine(store)}</p>
      </div>
      <AgentStatus />
    </header>
  );
}
