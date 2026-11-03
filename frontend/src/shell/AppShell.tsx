import { useEffect, useState } from "react";
import { Outlet, useLocation, useMatches, useNavigate } from "react-router";

import { AskPalette } from "./AskPalette";
import { Composer } from "./Composer";
import { HereContext } from "./here";
import { Suggestions } from "./Suggestions";
import { suggestedQuestions, useMorningBrief } from "@/conversation/morningBrief";
import { TOPIC_QUESTIONS } from "@/conversation/topics";
import { useConversation, type Topic } from "@/conversation/context";
import { ConversationProvider } from "@/conversation/ConversationProvider";
import { NavRail } from "./NavRail";
import { SIDEBAR, useSidebar } from "./sidebar";
import { TopBar } from "./TopBar";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";

/**
 * A route asks for the composer dock with `handle: { composer: true }` (Home, Conversations),
 * and for a wider column with `wide: true` (the decisions inbox: a list beside the decision).
 */
export interface RouteHandle {
  composer?: boolean;
  wide?: boolean;
}

function asks(handle: unknown, key: keyof RouteHandle): boolean {
  return typeof handle === "object" && handle !== null && (handle as RouteHandle)[key] === true;
}

/** The signed-in frame: the rail, the workspace header, the page, and the composer dock. */
export function AppShell() {
  const matches = useMatches();
  const composer = matches.some((match) => asks(match.handle, "composer"));
  const wide = matches.some((match) => asks(match.handle, "wide"));
  const sidebar = useSidebar();
  const beside = sidebar.collapsed ? SIDEBAR.besideCollapsed : SIDEBAR.besideExpanded;
  // On a phone the rail is a drawer, closed again by any navigation.
  const [drawer, setDrawer] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    setDrawer(false);
  }, [pathname]);
  // Ask from anywhere: ⌘K or Ctrl+K opens the palette, about what the page shows.
  const [here, setHere] = useState<Topic | null>(null);
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return (
    <ConversationProvider>
      <HereContext.Provider value={setHere}>
        <div className="min-h-dvh bg-canvas text-ink">
          <a
            href="#main"
            className="sr-only z-50 rounded-full bg-surface px-4 py-2 text-small text-ink focus:not-sr-only focus:fixed focus:top-3 focus:left-4 md:focus:left-24"
          >
            Skip to content
          </a>
          <NavRail
            collapsed={sidebar.collapsed}
            onToggle={sidebar.toggle}
            drawer={drawer}
            onClose={() => {
              setDrawer(false);
            }}
          />
          {drawer && (
            <div
              aria-hidden="true"
              className="fixed inset-0 z-20 bg-scrim md:hidden"
              onClick={() => {
                setDrawer(false);
              }}
            />
          )}
          <div
            className={cx(
              "flex min-h-dvh flex-col gap-8 px-4 pt-4 transition-[padding] duration-200 ease-out md:pt-6 md:pr-10",
              composer ? "pb-[240px]" : "pb-24",
              beside,
            )}
          >
            <TopBar
              onMenu={() => {
                setDrawer(true);
              }}
              onAsk={() => {
                setPalette(true);
              }}
            />
            <main
              id="main"
              tabIndex={-1}
              className={cx(
                "mx-auto flex w-full min-w-0 flex-col gap-6 outline-none",
                wide ? "max-w-[1120px]" : "max-w-[720px]",
              )}
            >
              <Outlet />
            </main>
          </div>
          {composer && (
            <div
              className={cx(
                "pointer-events-none fixed inset-x-0 bottom-0 z-10 bg-linear-to-t from-canvas from-60% to-transparent px-4 pt-8 pb-4 transition-[padding] duration-200 ease-out md:pr-10 md:pb-6",
                beside,
              )}
            >
              <div className="pointer-events-auto mx-auto w-full max-w-[720px]">
                <ConversationComposer />
              </div>
            </div>
          )}
        </div>
        {palette && (
          <AskPalette
            here={here}
            onClose={() => {
              setPalette(false);
            }}
          />
        )}
      </HereContext.Provider>
    </ConversationProvider>
  );
}

/**
 * The composer of the conversation: a question typed or said goes into it, and from Home it opens
 * Conversations to follow the answer. Until the first one, questions drawn from the morning brief
 * sit above it.
 */
function ConversationComposer() {
  const { ask, askByVoice, messages, topic, setTopic } = useConversation();
  const { brief } = useMorningBrief();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const asked = messages.some((m) => m.kind === "question");
  const follow = () => {
    if (!pathname.startsWith("/chat")) void navigate("/chat");
  };
  const typed = (question: string) => {
    ask(question);
    follow();
  };
  const said = (recording: Blob) => {
    askByVoice(recording);
    follow();
  };
  return (
    <div className="flex flex-col gap-3">
      {topic && (
        <p className="flex items-center gap-2 self-start rounded-full bg-subtle py-1 pr-1 pl-3 text-small text-ink">
          <span className="text-ink-muted">About</span>
          <span className="max-w-[48ch] truncate font-medium">{topic.label}</span>
          <button
            type="button"
            aria-label="Ask about the store as a whole"
            onClick={() => {
              setTopic(null);
            }}
            className="inline-flex size-6 cursor-pointer items-center justify-center rounded-full text-ink-muted hover:bg-line hover:text-ink"
          >
            <Icon name="x" size={14} />
          </button>
        </p>
      )}
      {topic ? (
        <Suggestions questions={TOPIC_QUESTIONS[topic.kind]} onPick={typed} />
      ) : (
        !asked && <Suggestions questions={suggestedQuestions(brief)} onPick={typed} />
      )}
      <Composer onSend={typed} onVoice={said} />
    </div>
  );
}
