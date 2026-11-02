/**
 * The icons exported from the Figma file, as downloaded (src/assets/icons). Each is drawn as a CSS
 * mask filled with the current text colour, so one file serves both themes and every state.
 */
import bookOpen from "@/assets/icons/book-open.svg";
import chevronUp from "@/assets/icons/chevron-up.svg";
import circleCheck from "@/assets/icons/circle-check.svg";
import fileCheck from "@/assets/icons/file-check.svg";
import flag from "@/assets/icons/flag.svg";
import flaskConical from "@/assets/icons/flask-conical.svg";
import lockKeyhole from "@/assets/icons/lock-keyhole.svg";
import messageCircle from "@/assets/icons/message-circle.svg";
import mic from "@/assets/icons/mic.svg";
import moon from "@/assets/icons/moon.svg";
import pause from "@/assets/icons/pause.svg";
import plus from "@/assets/icons/plus.svg";
import settings from "@/assets/icons/settings.svg";
import sun from "@/assets/icons/sun.svg";
import x from "@/assets/icons/x.svg";

/** Each icon's file and the size it was drawn at in Figma. */
export const ICONS = {
  "book-open": { url: bookOpen, size: 20 },
  "chevron-up": { url: chevronUp, size: 16 },
  "circle-check": { url: circleCheck, size: 20 },
  "file-check": { url: fileCheck, size: 16 },
  flag: { url: flag, size: 20 },
  "flask-conical": { url: flaskConical, size: 16 },
  "lock-keyhole": { url: lockKeyhole, size: 16 },
  "message-circle": { url: messageCircle, size: 20 },
  mic: { url: mic, size: 20 },
  moon: { url: moon, size: 20 },
  pause: { url: pause, size: 20 },
  plus: { url: plus, size: 20 },
  settings: { url: settings, size: 20 },
  sun: { url: sun, size: 20 },
  x: { url: x, size: 20 },
} as const;

export type IconName = keyof typeof ICONS;
