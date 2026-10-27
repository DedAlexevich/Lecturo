import { useCallback, useRef, useState } from "react";

export type Player = {
  seek: (seconds: number) => void;
  play: () => void;
  pause: () => void;
  getCurrentTime: () => number;
};

export type PlayerProps = {
  onReady: (player: Player | null) => void;
  onTimeUpdate: (seconds: number) => void;
};

export function videoIdentity(src: string) {
  return src.split("?")[0];
}

export function usePlayer() {
  const playerRef = useRef<Player | null>(null);
  const pendingSeek = useRef<number | null>(null);
  const pendingPlay = useRef(false);
  const [currentTime, setCurrentTime] = useState(0);

  const onReady = useCallback((player: Player | null) => {
    playerRef.current = player;
    if (!player) setCurrentTime(0);
    if (player && pendingSeek.current !== null) {
      player.seek(pendingSeek.current);
      pendingSeek.current = null;
    }
    if (player && pendingPlay.current) {
      pendingPlay.current = false;
      player.play();
    }
  }, []);

  const seek = useCallback((seconds: number) => {
    const player = playerRef.current;
    if (player) player.seek(seconds);
    else pendingSeek.current = seconds;
    setCurrentTime(seconds);
  }, []);

  const playFrom = useCallback(
    (seconds: number) => {
      seek(seconds);
      const player = playerRef.current;
      if (player) player.play();
      else pendingPlay.current = true;
    },
    [seek],
  );

  return {
    currentTime,
    seek,
    playFrom,
    bind: { onReady, onTimeUpdate: setCurrentTime } satisfies PlayerProps,
  };
}
