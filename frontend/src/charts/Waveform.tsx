import { useEffect, useRef } from "react";

const BARS = 48;

/**
 * The live waveform of a recording: bars as tall as the sound around them, redrawn each frame.
 * A picture only (it shows no number), in the current text colour.
 */
export function Waveform({ samples }: { samples: () => Uint8Array | null }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!element || !context) return;
    let frame = 0;
    const draw = () => {
      const { width, height } = element;
      context.clearRect(0, 0, width, height);
      context.fillStyle = getComputedStyle(element).color;
      const data = samples();
      const step = data ? Math.max(1, Math.floor(data.length / BARS)) : 1;
      const gap = width / BARS;
      for (let bar = 0; bar < BARS; bar += 1) {
        let peak = 0;
        for (let i = bar * step; data && i < Math.min(data.length, (bar + 1) * step); i += 1) {
          peak = Math.max(peak, Math.abs((data[i] ?? 128) - 128) / 128);
        }
        const tall = Math.max(2, peak * height);
        context.fillRect(bar * gap, (height - tall) / 2, Math.max(1, gap - 2), tall);
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [samples]);

  return (
    <canvas
      ref={canvas}
      aria-hidden="true"
      width={240}
      height={28}
      className="h-7 w-full min-w-0 flex-1 text-accent"
    />
  );
}
