import type { CSSProperties } from "react";

import { cx } from "./cx";
import { ICONS, type IconName } from "./icons";

interface IconProps {
  name: IconName;
  /** Pixels; the size the icon was drawn at by default. */
  size?: number;
  className?: string;
}

/** A decorative icon in the current text colour. Meaning is always carried by text next to it. */
export function Icon({ name, size, className }: IconProps) {
  const icon = ICONS[name];
  const side = `${String(size ?? icon.size)}px`;
  const mask = `url("${icon.url}")`;
  const style: CSSProperties = {
    width: side,
    height: side,
    maskImage: mask,
    WebkitMaskImage: mask,
    maskSize: "100% 100%",
    WebkitMaskSize: "100% 100%",
    maskRepeat: "no-repeat",
    WebkitMaskRepeat: "no-repeat",
  };
  return (
    <span
      aria-hidden="true"
      data-icon={name}
      className={cx("inline-block shrink-0 bg-current", className)}
      style={style}
    />
  );
}
