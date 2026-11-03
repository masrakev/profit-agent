/**
 * Questions to start from, so a composer never sits on a blank page: chosen by the page from the
 * store's own situation, sent as typed when picked.
 */
export function Suggestions({
  questions,
  onPick,
}: {
  questions: string[];
  onPick: (question: string) => void;
}) {
  if (questions.length === 0) return null;
  return (
    <ul
      aria-label="Suggested questions"
      className="-mx-4 flex gap-2 overflow-x-auto px-4 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0"
      data-stagger
    >
      {questions.map((question) => (
        <li key={question} className="shrink-0">
          <button
            type="button"
            onClick={() => {
              onPick(question);
            }}
            className="cursor-pointer rounded-full border whitespace-nowrap border-line bg-canvas px-3.5 py-1.5 text-small text-ink-muted transition-colors duration-150 hover:bg-subtle hover:text-ink"
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
