import asyncio
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, parse_qs, unquote, urlencode, urlparse

import httpx
import urllib3
from sqlalchemy.ext.asyncio import AsyncSession
from yt_dlp import YoutubeDL
from yt_dlp.networking._requests import RequestsRH
from yt_dlp.networking.exceptions import RequestError
from yt_dlp.utils import YoutubeDLError

from app.core.config import get_settings
from app.models import Lecture
from app.pipeline import media
from app.pipeline.media import MAX_DURATION_SEC, PROBE_TIMEOUT_SEC, make_mono
from app.pipeline.runner import Report, UserFacingError

logger = logging.getLogger(__name__)

PROGRESS_INTERVAL_SEC = 2.0
MAX_DOWNLOAD_BYTES = 2 * 1024**3
DOWNLOAD_TIMEOUT_SEC = 3600.0
MAX_REDIRECTS = 5
PROBE_FORMATS = "mov,matroska,mp3,ogg,wav,flac,aac,avi,flv,mpegts,asf"
INTERNAL_NETWORK = "Ссылка ведёт во внутреннюю сеть"

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
YANDEX_DISK_FOLDER_FILE = re.compile(r"(/d/[^/]+)(/.+)")
SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")

BASE_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "noprogress": True,
    "format": f"bestaudio[filesize<?{MAX_DOWNLOAD_BYTES}][filesize_approx<?{MAX_DOWNLOAD_BYTES}]"
    f"/best[filesize<?{MAX_DOWNLOAD_BYTES}][filesize_approx<?{MAX_DOWNLOAD_BYTES}]/bestaudio/best",
    "socket_timeout": 30,
    "retries": 3,
    "fragment_retries": 3,
    "extractor_retries": 2,
    "external_downloader": {"default": "native"},
    "external_downloader_args": {"ffmpeg_i": ["-protocol_whitelist", "file,crypto,data"]},
}


class LinkError(UserFacingError):
    pass


class BlockedAddress(RequestError):
    pass


def is_public_ip(address: str) -> bool:
    return ipaddress.ip_address(address).is_global


def public_address(host: str, port: int) -> str:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or not all(is_public_ip(sockaddr[0]) for *_, sockaddr in addresses):
        raise BlockedAddress(INTERNAL_NETWORK)
    ipv4 = [sockaddr[0] for family, *_, sockaddr in addresses if family == socket.AF_INET]
    return ipv4[0] if ipv4 else addresses[0][4][0]


class PublicHTTPConnection(urllib3.connection.HTTPConnection):
    def _new_conn(self):
        try:
            address = public_address(self._dns_host, self.port)
        except socket.gaierror as error:
            raise urllib3.exceptions.NameResolutionError(self.host, self, error) from error
        try:
            return urllib3.util.connection.create_connection(
                (address, self.port),
                self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options,
            )
        except TimeoutError as error:
            raise urllib3.exceptions.ConnectTimeoutError(
                self, f"Connection to {self.host} timed out"
            ) from error
        except OSError as error:
            raise urllib3.exceptions.NewConnectionError(
                self, f"Failed to establish a new connection: {error}"
            ) from error


class PublicHTTPSConnection(PublicHTTPConnection, urllib3.connection.HTTPSConnection):
    pass


class PublicHTTPConnectionPool(urllib3.HTTPConnectionPool):
    ConnectionCls = PublicHTTPConnection


class PublicHTTPSConnectionPool(urllib3.HTTPSConnectionPool):
    ConnectionCls = PublicHTTPSConnection


class PublicRequestsRH(RequestsRH):
    def _create_instance(self, cookiejar, legacy_ssl_support=None):
        session = super()._create_instance(cookiejar, legacy_ssl_support)
        for adapter in session.adapters.values():
            adapter.poolmanager.pool_classes_by_scheme = {
                "http": PublicHTTPConnectionPool,
                "https": PublicHTTPSConnectionPool,
            }
        return session


class PublicYoutubeDL(YoutubeDL):
    def build_request_director(self, handlers, preferences=None):
        return super().build_request_director([PublicRequestsRH], preferences)


@dataclass(frozen=True)
class LinkInfo:
    title: str | None
    duration: float
    embed_url: str | None


def normalized_host(parsed: ParseResult) -> str:
    return (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")


def is_yandex_disk(url: str) -> bool:
    return normalized_host(urlparse(url)) in YANDEX_DISK_HOSTS


def is_youtube(url: str) -> bool:
    host = normalized_host(urlparse(url))
    return host in YOUTUBE_HOSTS or host == "youtu.be"


def ydl_options(url: str) -> dict[str, Any]:
    proxy = get_settings().youtube_proxy
    if proxy and is_youtube(url):
        return {**BASE_OPTIONS, "proxy": proxy}
    return BASE_OPTIONS


def with_scheme(url: str) -> str:
    url = url.strip()
    if url and not SCHEME.match(url):
        return "https://" + url.removeprefix("//")
    return url


def youtube_id(parsed: ParseResult) -> str | None:
    host = normalized_host(parsed)
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host not in YOUTUBE_HOSTS:
        return None
    elif match := YOUTUBE_PATH.match(parsed.path):
        video_id = match.group(1)
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    return video_id if YOUTUBE_ID.fullmatch(video_id) else None


def rutube_id(parsed: ParseResult) -> str | None:
    if normalized_host(parsed) in RUTUBE_HOSTS and (match := RUTUBE_PATH.match(parsed.path)):
        return match.group(1)
    return None


def vk_params(parsed: ParseResult) -> dict[str, str] | None:
    if normalized_host(parsed) not in VK_HOSTS:
        return None
    query = parse_qs(parsed.query)
    if parsed.path == "/video_ext.php" and "oid" in query and "id" in query:
        params = {"oid": query["oid"][0], "id": query["id"][0]}
        if "hash" in query:
            params["hash"] = query["hash"][0]
        return params
    if match := VK_VIDEO.search(query.get("z", [""])[0]) or VK_VIDEO.search(parsed.path):
        return dict(zip(("oid", "id"), match.groups(), strict=True))
    return None


def build_embed_url(url: str) -> str | None:
    parsed = urlparse(url)
    if video_id := youtube_id(parsed):
        return f"https://www.youtube.com/embed/{video_id}"
    if video_id := rutube_id(parsed):
        embed = f"https://rutube.ru/play/embed/{video_id}"
        if private_key := parse_qs(parsed.query).get("p", [""])[0]:
            embed += "?" + urlencode({"p": private_key})
        return embed
    if params := vk_params(parsed):
        return "https://vkvideo.ru/video_ext.php?" + urlencode(params)
    return None


def link_key(url: str) -> str:
    parsed = urlparse(with_scheme(url))
    if video_id := youtube_id(parsed):
        return f"youtube:{video_id}"
    if video_id := rutube_id(parsed):
        return f"rutube:{video_id}"
    if params := vk_params(parsed):
        return f"vk:{params['oid']}_{params['id']}"
    host = normalized_host(parsed)
    if parsed.port is not None:
        host += f":{parsed.port}"
    path = unquote(parsed.path).rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{host}{path}{query}"


def yandex_disk_resource(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    if match := YANDEX_DISK_FOLDER_FILE.fullmatch(parsed.path.rstrip("/")):
        public_key = parsed._replace(path=match.group(1), query="", fragment="").geturl()
        return public_key, unquote(match.group(2))
    return url, None


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
        if not is_public_ip(sockaddr[0]):
            raise LinkError(INTERNAL_NETWORK)


async def follow_redirects(url: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await ensure_public_host(url)
                async with client.stream("GET", url) as response:
                    if not response.has_redirect_location:
                        return url
                    url = str(response.url.join(response.headers["location"]))
    except httpx.HTTPError as error:
        raise LinkError("Не удалось открыть ссылку") from error
    raise LinkError("Слишком много перенаправлений по ссылке")


async def resolve_yandex_disk(
    url: str, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, str]:
    public_key, path = yandex_disk_resource(url)
    params = {"public_key": public_key}
    if path is not None:
        params["path"] = path
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            resource = await client.get(YANDEX_DISK_API, params=params)
            if resource.status_code != httpx.codes.OK:
                raise LinkError("Файл на Яндекс Диске не найден или закрыт")
            meta = resource.json()
            if meta.get("type") != "file" or meta.get("media_type") not in {"video", "audio"}:
                raise LinkError("Ссылка Яндекс Диска должна вести на видео или аудиофайл")
            download = await client.get(f"{YANDEX_DISK_API}/download", params=params)
            if download.status_code != httpx.codes.OK:
                raise LinkError("Яндекс Диск не отдал ссылку на скачивание")
            return meta["name"], download.json()["href"]
    except (httpx.HTTPError, ValueError, KeyError, AttributeError) as error:
        raise LinkError("Яндекс Диск не ответил, попробуйте позже") from error


def extract_info(url: str) -> dict[str, Any]:
    with PublicYoutubeDL(ydl_options(url)) as ydl:
        return ydl.extract_info(url, download=False)


async def probe_duration(url: str) -> float | None:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "http,https,tls,tcp",
        "-max_redirects",
        "0",
        "-format_whitelist",
        PROBE_FORMATS,
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
        return None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
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
        except BlockedAddress as error:
            raise LinkError(INTERNAL_NETWORK) from error
        except YoutubeDLError as error:
            logger.warning("yt-dlp не смог получить видео (%s): %s", urlparse(url).hostname, error)
            raise LinkError("Не удалось получить видео по ссылке") from error
        if info.get("_type") == "playlist":
            raise LinkError("Нужна ссылка на одно видео, а не на плейлист")
        if info.get("is_live"):
            raise LinkError("Прямые трансляции не поддерживаются")
        title, embed_url, duration = info.get("title"), build_embed_url(url), info.get("duration")
        media_url = info.get("url") or url
    if not duration:
        duration = await probe_duration(await follow_redirects(media_url))
    if not duration:
        raise LinkError("Не удалось определить длительность видео")
    if duration > MAX_DURATION_SEC:
        raise LinkError("Видео длиннее 4 часов")
    return LinkInfo(title=title, duration=float(duration), embed_url=embed_url)


def fetch_audio(url: str, target: Path, progress: dict[str, float]) -> Path:
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SEC

    def on_progress(status: dict[str, Any]) -> None:
        if status["status"] != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        downloaded = status.get("downloaded_bytes", 0)
        if max(status.get("total_bytes") or 0, downloaded) > MAX_DOWNLOAD_BYTES:
            raise LinkError("Файл по ссылке больше 2 ГБ")
        if time.monotonic() > deadline:
            raise LinkError("Скачивание по ссылке заняло больше часа")
        if total:
            progress["fraction"] = downloaded / total

    options = {
        **ydl_options(url),
        "outtmpl": f"{target}.%(ext)s",
        "progress_hooks": [on_progress],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "48"}
        ],
        "postprocessor_args": {"extractaudio": ["-ac", "1"]},
    }
    with PublicYoutubeDL(options) as ydl:
        ydl.download([url])
    audio_path = target.with_suffix(".opus")
    if not audio_path.is_file():
        raise RuntimeError("Аудио не скачалось")
    return audio_path


def remove_partial(target: Path) -> None:
    for path in target.parent.glob(f"{target.name}.*"):
        path.unlink(missing_ok=True)


async def keep_progress(progress: float) -> None:
    pass


async def download(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    url = lecture.source_url or ""
    if is_yandex_disk(url):
        _, url = await resolve_yandex_disk(url)
    await ensure_public_host(url)
    audio_dir = get_settings().storage_dir / "audio"
    await asyncio.to_thread(audio_dir.mkdir, parents=True, exist_ok=True)
    target = audio_dir / str(lecture.id)
    progress = {"fraction": 0.0}
    fetching = asyncio.create_task(asyncio.to_thread(fetch_audio, url, target, progress))
    while not fetching.done():
        await asyncio.wait({fetching}, timeout=PROGRESS_INTERVAL_SEC)
        await report(progress["fraction"])
    try:
        audio_path = fetching.result()
    except Exception as error:
        await asyncio.to_thread(remove_partial, target)
        if isinstance(error, BlockedAddress):
            raise LinkError(INTERNAL_NETWORK) from error
        raise
    try:
        duration = await media.probe_duration(audio_path)
        if duration > MAX_DURATION_SEC:
            raise LinkError("Видео длиннее 4 часов")
        await make_mono(audio_path, duration, keep_progress)
    except Exception:
        await asyncio.to_thread(audio_path.unlink, missing_ok=True)
        raise
    lecture.audio_path = str(audio_path)
    lecture.duration_sec = duration
