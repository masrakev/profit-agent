import { createCn } from "cn/config";

/**
 * Joins class names and resolves Tailwind conflicts: the last of `h-10` and `h-9` wins. It knows
 * the design tokens of `src/styles/index.css`, so `text-small` is a size (not a colour) and
 * `rounded-card` a radius.
 */
export const cn = createCn({
  extend: {
    classGroups: {
      "font-size": [
        {
          text: [
            "body",
            "brand",
            "caption",
            "heading",
            "label",
            "nav",
            "proof",
            "small",
            "tiny",
            "title",
          ],
        },
      ],
      rounded: [{ rounded: ["avatar", "bar", "box", "bubble", "card", "destination", "mark"] }],
      shadow: [{ shadow: ["float", "sheet"] }],
    },
  },
});
