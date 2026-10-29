"""Text hygiene shared by everything that handles merchant-provided text.

The character classes are built from code points so that no invisible character ever appears in
the source itself.
"""

import re

# C0 and C1 controls (except tab, line feed and carriage return, handled as line breaks),
# zero-width characters, bidirectional embeddings, overrides and isolates, invisible operators
# and the byte-order mark.
INVISIBLE_RANGES = (
    (0x00, 0x08),
    (0x0B, 0x0C),
    (0x0E, 0x1F),
    (0x7F, 0x9F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
)
INVISIBLE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in INVISIBLE_RANGES) + "]")
LINE_BREAK_CODES = (0x09, 0x0A, 0x0D, 0x2028, 0x2029)
LINE_BREAKS = re.compile("[" + "".join(re.escape(chr(c)) for c in LINE_BREAK_CODES) + "]+")


def strip_invisible(text: str) -> str:
    return INVISIBLE.sub("", text)
