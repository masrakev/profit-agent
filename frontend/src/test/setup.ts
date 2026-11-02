/// <reference types="node" />
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// The suite passes on any day: `TEST_CLOCK=2026-12-15T12:00:00Z npm test` runs it with the date
// moved there (only Date is faked, and it keeps ticking; timers stay real).
const clock = process.env["TEST_CLOCK"];
if (clock) vi.useFakeTimers({ now: new Date(clock), toFake: ["Date"], shouldAdvanceTime: true });

afterEach(() => {
  cleanup();
  document.cookie.split(";").forEach((cookie) => {
    const name = cookie.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
});
