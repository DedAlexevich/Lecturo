import { useRef, useState } from "react";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import type { ZoomerMode } from "./useZoomerMode";
import "./zoomer.css";

export function ZoomerToggle({ mode }: { mode: ZoomerMode }) {
  if (!mode.available) return null;
  return (
    <>
      <Button
        variant={mode.clip !== null ? "secondary" : "ghost"}
        size="sm"
        aria-pressed={mode.clip !== null}
        onClick={mode.toggle}
      >
        Режим зумера
      </Button>
      <Dialog
        open={mode.confirming}
        onClose={mode.cancel}
        title="Включить режим зумера?"
        actions={
          <>
            <Button variant="secondary" onClick={mode.cancel}>
              Отмена
            </Button>
            <Button onClick={mode.enable}>Включить</Button>
          </>
        }
      >
        <p>
          В системе включено уменьшение движения. В режиме зумера рядом с плеером без остановки крутится
          видео без звука. Его можно скрыть в любой момент.
        </p>
      </Dialog>
    </>
  );
}

export function ZoomerClip({ src, autoplay, onHide }: { src: string; autoplay: boolean; onHide: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  return (
    <aside className="zoomer" aria-label="Режим зумера">
      <div className="zoomer__frame">
        <video
          ref={video}
          key={src}
          className="zoomer__video"
          src={src}
          muted
          loop
          playsInline
          autoPlay={autoplay}
          preload={autoplay ? "auto" : "metadata"}
          disablePictureInPicture
          aria-hidden="true"
          tabIndex={-1}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        {!playing && !autoplay && (
          <button type="button" className="zoomer__start" onClick={() => void video.current?.play()}>
            Запустить
          </button>
        )}
      </div>
      <Button variant="ghost" size="sm" className="zoomer__hide" onClick={onHide}>
        Скрыть
      </Button>
    </aside>
  );
}
