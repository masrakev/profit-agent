import { describe, expect, it } from "vitest";

import { modelName, workingModel } from "./models";

describe("Meta's models, by name", () => {
  it("reads the id the API reports as people name the model", () => {
    expect(modelName("muse-spark-1.3")).toBe("Muse Spark 1.3");
    expect(modelName("muse-spark-1.3-contributor")).toBe("Muse Spark 1.3");
    expect(modelName("muse-wonder-1.0")).toBe("Muse Wonder 1.0");
    expect(modelName("meta-models/muse-spark-open-1026")).toBe("Muse Spark Open");
    expect(modelName("muse-voice-transcribe-1.0")).toBe("Muse Voice");
    expect(modelName("another-model")).toBe("another-model");
    expect(modelName(null)).toBeNull();
  });

  it("names the model of the last call, an escalation included", () => {
    const step = (name: string | null) => ({ kind: "model", name, detail: {} });
    const tool = { kind: "tool", name: "get_inventory_context", detail: {} };
    expect(workingModel([tool])).toBeNull();
    expect(workingModel([step("muse-spark-1.3"), tool, step("muse-wonder-1.0")])).toBe(
      "Muse Wonder 1.0",
    );
  });
});
