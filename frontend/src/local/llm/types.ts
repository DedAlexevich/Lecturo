export type LlmPrecision = "f16" | "f32";

export interface OutlineProgress {
  stage: "loading" | "outlining";
  value: number;
}

export type OutlineProgressHandler = (progress: OutlineProgress) => void;
