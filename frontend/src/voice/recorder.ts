/**
 * Recording a spoken question in the browser: the microphone through MediaRecorder (WebM/Opus in
 * Chrome and Firefox, MP4/AAC in Safari: the API takes both) and an analyser for the waveform.
 * The recording stays in memory until it is sent; nothing is stored in the browser.
 */

export const MAX_SECONDS = 120; // the API refuses a question over two minutes

export interface Recorder {
  /** Asks for the microphone and starts recording. */
  start: () => Promise<void>;
  /** Stops and returns the recording. */
  stop: () => Promise<Blob>;
  /** Stops and drops it. */
  cancel: () => void;
  /** The current sound, as time-domain samples (128 is silence), for the waveform. */
  samples: () => Uint8Array | null;
}

export type RecorderFactory = () => Recorder;

export class RecordingUnavailable extends Error {}

export const createRecorder: RecorderFactory = () => {
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let context: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let buffer: Uint8Array<ArrayBuffer> | null = null;
  const chunks: Blob[] = [];

  const release = () => {
    stream?.getTracks().forEach((track) => {
      track.stop();
    });
    void context?.close();
    stream = null;
    context = null;
    analyser = null;
  };

  return {
    async start() {
      if (typeof MediaRecorder === "undefined" || !("mediaDevices" in navigator)) {
        throw new RecordingUnavailable("this browser cannot record");
      }
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream);
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      });
      context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
      buffer = new Uint8Array(analyser.fftSize);
      context.createMediaStreamSource(stream).connect(analyser);
      recorder.start();
    },
    stop() {
      return new Promise<Blob>((resolve) => {
        const active = recorder;
        if (!active || active.state === "inactive") {
          resolve(new Blob(chunks));
          return;
        }
        active.addEventListener("stop", () => {
          resolve(new Blob(chunks, { type: active.mimeType }));
          release();
        });
        active.stop();
      });
    },
    cancel() {
      if (recorder && recorder.state !== "inactive") recorder.stop();
      chunks.length = 0;
      release();
    },
    samples() {
      if (!analyser || !buffer) return null;
      analyser.getByteTimeDomainData(buffer);
      return buffer;
    },
  };
};
