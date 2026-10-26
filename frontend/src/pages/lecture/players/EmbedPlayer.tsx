import { useEffect, useRef, useState } from "react";
import { Spinner } from "../../../ui/Spinner";
import type { Embed, EmbedStart } from "./embed";
import type { PlayerProps } from "./player";
import "./EmbedPlayer.css";

const READY_TIMEOUT_MS = 10000;

type EmbedPlayerProps = PlayerProps & {
  embed: Embed;
  title: string;
  start: number;
  sourceUrl: string | null;
};

type Load = EmbedStart & { attempt: number };

export function EmbedPlayer({ embed, title, start, sourceUrl, onReady, onTimeUpdate }: EmbedPlayerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [load, setLoad] = useState<Load>({ seconds: start, autoplay: false, attempt: 0 });
  const [loading, setLoading] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const { provider } = embed;
  const src = provider.buildSrc(embed.url, load);

  useEffect(() => () => onReady(null), [onReady]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const timeout = window.setTimeout(() => {
      setDegraded(true);
      onReady({
        seek: (seconds) => {
          const target = Math.max(0, seconds);
          setLoad((current) => ({ seconds: target, autoplay: true, attempt: current.attempt + 1 }));
          onTimeUpdate(target);
        },
        play: () => undefined,
        pause: () => undefined,
        getCurrentTime: () => load.seconds,
      });
    }, READY_TIMEOUT_MS);
    const disconnect = provider.connect(iframe, {
      onReady: (player) => {
        window.clearTimeout(timeout);
        setDegraded(false);
        onReady(player);
      },
      onTimeUpdate,
    });
    return () => {
      window.clearTimeout(timeout);
      disconnect();
    };
  }, [provider, src, load.attempt, load.seconds, onReady, onTimeUpdate]);

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
        {sourceUrl && (
          <a href={sourceUrl} target="_blank" rel="noreferrer" className="embed-player__source">
            Открыть на площадке
          </a>
        )}
      </figcaption>
    </figure>
  );
}
