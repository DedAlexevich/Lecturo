import { useCallback, useState } from "react";
import { zoomerClips } from "./clips";
import { nextClipIndex, parseStoredIndex, parseStoredMode } from "./rotation";

const modeKey = "lecturo-zoomer";
const clipKey = "lecturo-zoomer-clip";

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function pickClip(): string | null {
  const index = nextClipIndex(parseStoredIndex(readStorage(clipKey)), zoomerClips.length);
  if (index === null) return null;
  writeStorage(clipKey, String(index));
  return zoomerClips[index];
}

export function useZoomerMode() {
  const available = zoomerClips.length > 0;
  const [clip, setClip] = useState<string | null>(() =>
    available && parseStoredMode(readStorage(modeKey)) ? pickClip() : null,
  );
  const [autoplay, setAutoplay] = useState(() => !prefersReducedMotion());
  const [confirming, setConfirming] = useState(false);

  const enable = useCallback(() => {
    setConfirming(false);
    setAutoplay(true);
    setClip(pickClip());
    writeStorage(modeKey, "on");
  }, []);

  const disable = useCallback(() => {
    setClip(null);
    writeStorage(modeKey, null);
  }, []);

  const toggle = useCallback(() => {
    if (clip !== null) disable();
    else if (prefersReducedMotion()) setConfirming(true);
    else enable();
  }, [clip, disable, enable]);

  const cancel = useCallback(() => setConfirming(false), []);

  return { available, clip, autoplay, confirming, toggle, enable, disable, cancel };
}

export type ZoomerMode = ReturnType<typeof useZoomerMode>;
