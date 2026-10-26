import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Spinner } from "../../../ui/Spinner";
import { formatTimecode } from "../time";
import type { PlayerProps } from "./player";
import "./VideoPlayer.css";

const RATES = [1, 1.25, 1.5, 1.75, 2];
const STEP_SECONDS = 5;

type VideoPlayerProps = PlayerProps & {
  src: string;
  title: string;
};

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d={path} fill="currentColor" />
    </svg>
  );
}

const icons = {
  play: "M8 5.5v13a1 1 0 0 0 1.5.86l10.6-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z",
  pause: "M7 5h3.5v14H7zM13.5 5H17v14h-3.5z",
  volume: "M4 9h4l5-4v14l-5-4H4zM16 8.5a5 5 0 0 1 0 7l-1.4-1.4a3 3 0 0 0 0-4.2zM18.4 6a8.5 8.5 0 0 1 0 12L17 16.6a6.5 6.5 0 0 0 0-9.2z",
  muted: "M4 9h4l5-4v14l-5-4H4zM16.3 9.7l1.4-1.4L20 10.6l2.3-2.3 1.4 1.4-2.3 2.3 2.3 2.3-1.4 1.4-2.3-2.3-2.3 2.3-1.4-1.4 2.3-2.3z",
  enterFullscreen: "M4 4h6v2H6v4H4zM14 4h6v6h-2V6h-4zM4 14h2v4h4v2H4zM18 14h2v6h-6v-2h4z",
  exitFullscreen: "M8 4h2v6H4V8h4zM14 4h2v4h4v2h-6zM4 14h6v6H8v-4H4zM14 14h6v2h-4v4h-2z",
};

export function VideoPlayer({ src, title, onReady, onTimeUpdate }: VideoPlayerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState(1);
  const [muted, setMuted] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [failed, setFailed] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => () => onReady(null), [onReady]);

  const video = () => videoRef.current;

  const seekTo = (seconds: number) => {
    const element = video();
    if (!element) return;
    const limit = Number.isFinite(element.duration) ? element.duration : seconds;
    element.currentTime = Math.min(Math.max(0, seconds), limit);
    setTime(element.currentTime);
    onTimeUpdate(element.currentTime);
  };

  const togglePlay = () => {
    const element = video();
    if (!element) return;
    if (element.paused) void element.play().catch(() => undefined);
    else element.pause();
  };

  const toggleMute = () => {
    const element = video();
    if (!element) return;
    element.muted = !element.muted;
    setMuted(element.muted);
  };

  const changeRate = (value: number) => {
    const element = video();
    if (element) element.playbackRate = value;
    setRate(value);
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void rootRef.current?.requestFullscreen?.();
  };

  const onLoadedMetadata = () => {
    const element = video();
    if (!element) return;
    setDuration(element.duration);
    onReady({
      seek: seekTo,
      play: () => void element.play().catch(() => undefined),
      pause: () => element.pause(),
      getCurrentTime: () => element.currentTime,
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    const element = video();
    if (!element || event.altKey || event.ctrlKey || event.metaKey) return;
    const actions: Record<string, () => void> = {
      " ": togglePlay,
      k: togglePlay,
      ArrowLeft: () => seekTo(element.currentTime - STEP_SECONDS),
      ArrowRight: () => seekTo(element.currentTime + STEP_SECONDS),
      m: toggleMute,
      f: toggleFullscreen,
    };
    const action = actions[event.key];
    if (!action) return;
    if (event.key === " " && event.target instanceof HTMLButtonElement) return;
    event.preventDefault();
    action();
  };

  const progress = duration > 0 ? Math.min(1, time / duration) : 0;

  return (
    <div
      ref={rootRef}
      className={fullscreen ? "video-player video-player--fullscreen" : "video-player"}
      onKeyDown={onKeyDown}
    >
      <div className="video-player__screen">
        <video
          ref={videoRef}
          className="video-player__video"
          src={src}
          preload="metadata"
          playsInline
          aria-label={title}
          onClick={togglePlay}
          onLoadedMetadata={onLoadedMetadata}
          onDurationChange={(event) => setDuration(event.currentTarget.duration)}
          onTimeUpdate={(event) => {
            setTime(event.currentTarget.currentTime);
            onTimeUpdate(event.currentTarget.currentTime);
          }}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onWaiting={() => setWaiting(true)}
          onPlaying={() => setWaiting(false)}
          onCanPlay={() => setWaiting(false)}
          onError={() => setFailed(true)}
        />
        {waiting && !failed && (
          <div className="video-player__overlay">
            <Spinner size="lg" label="Видео загружается" />
          </div>
        )}
        {failed && (
          <div className="video-player__overlay video-player__overlay--error" role="alert">
            Не удалось загрузить видео. Обновите страницу или попробуйте позже.
          </div>
        )}
      </div>
      <div className="video-player__controls">
        <div className="video-player__track">
          <div className="video-player__rail">
            <div className="video-player__fill" style={{ transform: `scaleX(${progress})` }} />
          </div>
          <input
            className="video-player__seek"
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(time, duration || 0)}
            disabled={failed || duration === 0}
            aria-label="Перемотка"
            aria-valuetext={`${formatTimecode(time)} из ${formatTimecode(duration)}`}
            onChange={(event) => seekTo(Number(event.currentTarget.value))}
          />
        </div>
        <div className="video-player__bar">
          <button
            type="button"
            className="video-player__button"
            onClick={togglePlay}
            disabled={failed}
            aria-label={playing ? "Пауза" : "Смотреть"}
          >
            <Icon path={playing ? icons.pause : icons.play} />
          </button>
          <span className="video-player__time">
            {formatTimecode(time)}
            <span className="video-player__duration"> / {formatTimecode(duration)}</span>
          </span>
          <label className="video-player__rate">
            <span className="video-player__rate-label">Скорость</span>
            <select value={rate} onChange={(event) => changeRate(Number(event.currentTarget.value))}>
              {RATES.map((value) => (
                <option key={value} value={value}>
                  {`${value}×`}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="video-player__button"
            onClick={toggleMute}
            aria-label={muted ? "Включить звук" : "Выключить звук"}
            aria-pressed={muted}
          >
            <Icon path={muted ? icons.muted : icons.volume} />
          </button>
          <button
            type="button"
            className="video-player__button"
            onClick={toggleFullscreen}
            aria-label={fullscreen ? "Выйти из полноэкранного режима" : "Во весь экран"}
          >
            <Icon path={fullscreen ? icons.exitFullscreen : icons.enterFullscreen} />
          </button>
        </div>
      </div>
    </div>
  );
}
