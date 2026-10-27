import { useCallback, useEffect, useState } from "react";
import { loadZoomerClips } from "./clips";
import { nextClipIndex, parseStoredIndex, parseStoredMode } from "./rotation";

const modeKey = "lecturo-zoomer";
const clipKey = "lecturo-zoomer-clip";

const missingKey = "lecturo-zoomer-missing";

function readStorage(key: string, session = false): string | null {
  try {
    return (session ? sessionStorage : localStorage).getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null, session = false) {
  try {
    const storage = session ? sessionStorage : localStorage;
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, value);
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

export function useZoomerMode() {
  const [missing, setMissing] = useState(() => readStorage(missingKey, true) !== null);
  const [enabled, setEnabled] = useState(() => !missing && parseStoredMode(readStorage(modeKey)));
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
    if (!enabled || clips !== null) return;
    let active = true;
    void loadZoomerClips().then((loaded) => {
      if (active) setClips(loaded);
    });
    return () => {
      active = false;
    };
  }, [enabled, clips]);

  useEffect(() => {
    if (!enabled || clips === null) return;
    if (clips.length === 0) {
      writeStorage(missingKey, "1", true);
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
    available: !missing,
    enabled,
    clip: enabled ? clip : null,
    autoplay,
    confirming,
    toggle,
    enable,
    disable,
    cancel,
  };
}

export type ZoomerMode = ReturnType<typeof useZoomerMode>;
