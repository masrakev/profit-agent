import { afterEach, describe, expect, it, vi } from "vitest";

import { createRecorder, RecordingUnavailable } from "./recorder";

class FakeMediaRecorder extends EventTarget {
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm;codecs=opus";
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    const data = Object.assign(new Event("dataavailable"), { data: new Blob(["sound"]) });
    this.dispatchEvent(data);
    this.dispatchEvent(
      Object.assign(new Event("dataavailable"), { data: new Blob([]) }), // an empty chunk is skipped
    );
    this.dispatchEvent(new Event("stop"));
  }
}

const track = { stop: vi.fn() };
const analyser = {
  fftSize: 0,
  getByteTimeDomainData: vi.fn((buffer: Uint8Array) => buffer.fill(130)),
};
const context = {
  createAnalyser: () => analyser,
  createMediaStreamSource: () => ({ connect: vi.fn() }),
  close: vi.fn(() => Promise.resolve()),
};

function microphone() {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function AudioContext() {
      return context;
    }),
  );
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(() => Promise.resolve({ getTracks: () => [track] })) },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
  vi.clearAllMocks();
});

describe("the recorder", () => {
  it("records from the microphone, with the sound for the waveform", async () => {
    microphone();
    const recorder = createRecorder();
    expect(recorder.samples()).toBeNull();
    await recorder.start();
    expect(recorder.samples()?.[0]).toBe(130);
    const recording = await recorder.stop();
    expect(recording.type).toBe("audio/webm;codecs=opus");
    expect(recording.size).toBe(5);
    expect(track.stop).toHaveBeenCalledOnce();
    expect(context.close).toHaveBeenCalledOnce();
    expect(recorder.samples()).toBeNull();
    expect((await recorder.stop()).size).toBe(5); // stopped already: the same recording
  });

  it("drops the recording when cancelled", async () => {
    microphone();
    const recorder = createRecorder();
    await recorder.start();
    recorder.cancel();
    expect(track.stop).toHaveBeenCalledOnce();
    expect((await recorder.stop()).size).toBe(0);
    recorder.cancel(); // nothing left to stop
  });

  it("says when the browser cannot record", async () => {
    await expect(createRecorder().start()).rejects.toBeInstanceOf(RecordingUnavailable);
  });
});
