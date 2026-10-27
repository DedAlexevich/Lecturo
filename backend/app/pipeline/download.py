import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, parse_qs, urlencode, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError

from app.core.config import get_settings
from app.models import Lecture
from app.pipeline.media import MAX_DURATION_SEC, PROBE_TIMEOUT_SEC
from app.pipeline.runner import Report

logger = logging.getLogger(__name__)

PROGRESS_INTERVAL_SEC = 2.0

YANDEX_DISK_HOSTS = {
    "disk.yandex.ru",
    "disk.yandex.com",
    "disk.yandex.by",
    "disk.yandex.kz",
    "yadi.sk",
}
YANDEX_DISK_API = "https://cloud-api.yandex.net/v1/disk/public/resources"
YOUTUBE_HOSTS = {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}
RUTUBE_HOSTS = {"rutube.ru"}
VK_HOSTS = {"vk.com", "vk.ru", "vkvideo.ru"}

YOUTUBE_PATH = re.compile(r"/(?:shorts|embed|live|v)/([\w-]{11})")
YOUTUBE_ID = re.compile(r"[\w-]{11}")
RUTUBE_PATH = re.compile(r"/(?:video|play/embed)/(?:private/)?([0-9a-f]{32})")
VK_VIDEO = re.compile(r"video(-?\d+)_(\d+)")

BASE_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "noprogress": True,
    "format": "bestaudio/best",
    "socket_timeout": 30,
    "retries": 3,
    "fragment_retries": 3,
    "extractor_retries": 2,
}


class LinkError(Exception):
    pass


@dataclass(frozen=True)
class LinkInfo:
    title: str | None
    duration: float
    embed_url: str | None


def normalized_host(parsed: ParseResult) -> str:
    return (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")


def is_yandex_disk(url: str) -> bool:
    return normalized_host(urlparse(url)) in YANDEX_DISK_HOSTS


def build_embed_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = normalized_host(parsed)
    query = parse_qs(parsed.query)
    if host in YOUTUBE_HOSTS or host == "youtu.be":
        if host == "youtu.be":
            video_id = parsed.path.strip("/")
        elif match := YOUTUBE_PATH.match(parsed.path):
            video_id = match.group(1)
        else:
            video_id = query.get("v", [""])[0]
        if YOUTUBE_ID.fullmatch(video_id):
            return f"https://www.youtube.com/embed/{video_id}"
    if host in RUTUBE_HOSTS and (match := RUTUBE_PATH.match(parsed.path)):
        embed = f"https://rutube.ru/play/embed/{match.group(1)}"
        if private_key := query.get("p", [""])[0]:
            embed += "?" + urlencode({"p": private_key})
        return embed
    if host in VK_HOSTS:
        if parsed.path == "/video_ext.php" and "oid" in query and "id" in query:
            params = {"oid": query["oid"][0], "id": query["id"][0]}
            if "hash" in query:
                params["hash"] = query["hash"][0]
        elif match := VK_VIDEO.search(query.get("z", [""])[0]) or VK_VIDEO.search(parsed.path):
            params = dict(zip(("oid", "id"), match.groups(), strict=True))
        else:
            return None
        return "https://vkvideo.ru/video_ext.php?" + urlencode(params)
    return None


async def ensure_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LinkError("Поддерживаются только ссылки http и https")
    host = parsed.hostname
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(host, None)
    except socket.gaierror as error:
        raise LinkError("Не удалось открыть ссылку") from error
    for *_, sockaddr in addresses:
        if not ipaddress.ip_address(sockaddr[0]).is_global:
            raise LinkError("Ссылка ведёт во внутреннюю сеть")


async def resolve_yandex_disk(
    url: str, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            resource = await client.get(YANDEX_DISK_API, params={"public_key": url})
            if resource.status_code != httpx.codes.OK:
                raise LinkError("Файл на Яндекс Диске не найден или закрыт")
            meta = resource.json()
            if meta.get("type") != "file" or meta.get("media_type") not in {"video", "audio"}:
                raise LinkError("Ссылка Яндекс Диска должна вести на видео или аудиофайл")
            download = await client.get(f"{YANDEX_DISK_API}/download", params={"public_key": url})
            if download.status_code != httpx.codes.OK:
                raise LinkError("Яндекс Диск не отдал ссылку на скачивание")
            return meta["name"], download.json()["href"]
    except (httpx.HTTPError, ValueError, KeyError, AttributeError) as error:
        raise LinkError("Яндекс Диск не ответил, попробуйте позже") from error


def extract_info(url: str) -> dict[str, Any]:
    with YoutubeDL(BASE_OPTIONS) as ydl:
        return ydl.extract_info(url, download=False)


async def probe_duration(url: str) -> float | None:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "http,https,tls,tcp",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), PROBE_TIMEOUT_SEC)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return None


async def inspect_link(url: str) -> LinkInfo:
    await ensure_public_host(url)
    if is_yandex_disk(url):
        name, media_url = await resolve_yandex_disk(url)
        title, embed_url, duration = Path(name).stem, None, None
    else:
        try:
            info = await asyncio.to_thread(extract_info, url)
        except YoutubeDLError as error:
            logger.warning("yt-dlp не смог получить %s: %s", url, error)
            raise LinkError("Не удалось получить видео по ссылке") from error
        if info.get("_type") == "playlist":
            raise LinkError("Нужна ссылка на одно видео, а не на плейлист")
        if info.get("is_live"):
            raise LinkError("Прямые трансляции не поддерживаются")
        title, embed_url, duration = info.get("title"), build_embed_url(url), info.get("duration")
        media_url = info.get("url") or url
    if not duration:
        await ensure_public_host(media_url)
        duration = await probe_duration(media_url)
    if not duration:
        raise LinkError("Не удалось определить длительность видео")
    if duration > MAX_DURATION_SEC:
        raise LinkError("Видео длиннее 4 часов")
    return LinkInfo(title=title, duration=float(duration), embed_url=embed_url)


def fetch_audio(url: str, target: Path, progress: dict[str, float]) -> Path:
    def on_progress(status: dict[str, Any]) -> None:
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        if status["status"] == "downloading" and total:
            progress["fraction"] = status.get("downloaded_bytes", 0) / total

    options = {
        **BASE_OPTIONS,
        "outtmpl": f"{target}.%(ext)s",
        "progress_hooks": [on_progress],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "48"}
        ],
        "postprocessor_args": {"extractaudio": ["-ac", "1"]},
    }
    with YoutubeDL(options) as ydl:
        ydl.download([url])
    audio_path = target.with_suffix(".opus")
    if not audio_path.is_file():
        raise RuntimeError("Аудио не скачалось")
    return audio_path


async def download(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    url = lecture.source_url or ""
    if is_yandex_disk(url):
        _, url = await resolve_yandex_disk(url)
    await ensure_public_host(url)
    audio_dir = get_settings().storage_dir / "audio"
    await asyncio.to_thread(audio_dir.mkdir, parents=True, exist_ok=True)
    progress = {"fraction": 0.0}
    fetching = asyncio.create_task(
        asyncio.to_thread(fetch_audio, url, audio_dir / str(lecture.id), progress)
    )
    while not fetching.done():
        await asyncio.wait({fetching}, timeout=PROGRESS_INTERVAL_SEC)
        await report(progress["fraction"])
    lecture.audio_path = str(fetching.result())
