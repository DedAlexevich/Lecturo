import { useCallback, useEffect, useState } from "react";
import { loadZoomerClips } from "./clips";
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

function pickClip(clips: string[]): string | null {
  const index = nextClipIndex(parseStoredIndex(readStorage(clipKey)), clips.length);
  if (index === null) return null;
  writeStorage(clipKey, String(index));
  return clips[index];
}

export function useZoomerMode(allowed: boolean) {
  const [missing, setMissing] = useState(false);
  const [enabled, setEnabled] = useState(() => parseStoredMode(readStorage(modeKey)));
  const [clips, setClips] = useState<string[] | null>(null);
  const [clip, setClip] = useState<string | null>(null);
  const [autoplay, setAutoplay] = useState(() => !prefersReducedMotion());
  const [confirming, setConfirming] = useState(false);

  const disable = useCallback(() => {
    setEnabled(false);
    setClip(null);
    writeStorage(modeKey, null);
  }, []);

  useEffect(() => {
    if (!allowed || !enabled || clips !== null) return;
    let active = true;
    void loadZoomerClips().then((loaded) => {
      if (active) setClips(loaded);
    });
    return () => {
      active = false;
    };
  }, [allowed, enabled, clips]);

  useEffect(() => {
    if (!enabled || clips === null) return;
    if (clips.length === 0) {
      setMissing(true);
      disable();
      return;
    }
    writeStorage(modeKey, "on");
    if (clip === null) setClip(pickClip(clips));
  }, [enabled, clips, clip, disable]);

  const enable = useCallback(() => {
    setConfirming(false);
    setAutoplay(true);
    setEnabled(true);
  }, []);

  const toggle = useCallback(() => {
    if (enabled) disable();
    else if (prefersReducedMotion()) setConfirming(true);
    else enable();
  }, [enabled, disable, enable]);

  const cancel = useCallback(() => setConfirming(false), []);

  return {
    available: allowed && !missing,
    enabled,
    clip: allowed && enabled ? clip : null,
    autoplay,
    confirming,
    toggle,
    enable,
    disable,
    cancel,
  };
}

export type ZoomerMode = ReturnType<typeof useZoomerMode>;
