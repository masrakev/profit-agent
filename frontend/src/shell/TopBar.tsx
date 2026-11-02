import { ConnectionStatus } from "./ConnectionStatus";
import { storeLine, useStore } from "@/stores/store";
import { BrandMark } from "@/ui/BrandMark";

/** The workspace header: the store on the left, the brand in the middle, the connection right. */
export function TopBar() {
  const store = useStore();
  return (
    <header className="grid h-10 grid-cols-[1fr_auto_1fr] items-center gap-4">
      <p className="truncate text-label text-ink-muted">{storeLine(store)}</p>
      <BrandMark named />
      <div className="flex justify-end">
        <ConnectionStatus />
      </div>
    </header>
  );
}
