import { useEffect, useRef, useState } from "react";
import { Spinner } from "../../../ui/Spinner";
import type { Embed, EmbedStart } from "./embed";
import type { PlayerProps } from "./player";
import "./EmbedPlayer.css";

const READY_TIMEOUT_MS = 3000;

type EmbedPlayerProps = PlayerProps & {
  embed: Embed;
  title: string;
  start: number;
  currentTime: number;
  sourceUrl: string | null;
};

type Load = EmbedStart & { attempt: number };

export function EmbedPlayer({ embed, title, start, currentTime, sourceUrl, onReady, onTimeUpdate }: EmbedPlayerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const positionRef = useRef(start);
  const [load, setLoad] = useState<Load>({ seconds: start, autoplay: false, attempt: 0 });
  const [loading, setLoading] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const { provider } = embed;
  const src = provider.buildSrc(embed.url, load);
  const sourceLink = sourceUrl ? provider.linkAt(sourceUrl, currentTime) : null;

  const handlersRef = useRef({ onReady, onTimeUpdate });

  useEffect(() => {
    handlersRef.current = { onReady, onTimeUpdate };
  }, [onReady, onTimeUpdate]);

  useEffect(() => () => onReady(null), [onReady]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const { onReady, onTimeUpdate } = handlersRef.current;
    const report = (seconds: number) => {
      positionRef.current = seconds;
      onTimeUpdate(seconds);
    };
    const timeout = window.setTimeout(() => {
      setDegraded(true);
      onReady({
        seek: (seconds) => {
          const target = Math.max(0, seconds);
          setLoading(true);
          setLoad((current) => ({ seconds: target, autoplay: true, attempt: current.attempt + 1 }));
          report(target);
        },
        play: () => undefined,
        pause: () => undefined,
        getCurrentTime: () => positionRef.current,
      });
    }, READY_TIMEOUT_MS);
    const disconnect = provider.connect(iframe, {
      onReady: (player) => {
        window.clearTimeout(timeout);
        setDegraded(false);
        onReady(player);
      },
      onTimeUpdate: report,
    });
    return () => {
      window.clearTimeout(timeout);
      disconnect();
    };
  }, [provider, src, load.attempt]);

  return (
    <figure className="embed-player">
      <div className="embed-player__screen">
        <iframe
          key={load.attempt}
          ref={iframeRef}
          className="embed-player__frame"
          src={src}
          title={`${provider.name}: ${title}`}
          allow="autoplay; encrypted-media; fullscreen; picture-in-picture; clipboard-write"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
          onLoad={() => setLoading(false)}
        />
        {loading && (
          <div className="embed-player__overlay">
            <Spinner size="lg" label="Плеер загружается" />
          </div>
        )}
      </div>
      <figcaption className="embed-player__caption">
        <span className="embed-player__note">
          {degraded
            ? `Плеер ${provider.name} не отвечает, поэтому переход к фразе перезагружает видео с нужного места.`
            : `Видео с ${provider.name}`}
        </span>
        {sourceLink && (
          <a href={sourceLink} target="_blank" rel="noreferrer" className="embed-player__source">
            Открыть на площадке с этого места
          </a>
        )}
      </figcaption>
    </figure>
  );
}
