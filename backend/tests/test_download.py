import functools
import uuid
import wave
from pathlib import Path

import httpx
import pytest

from app.models import Lecture, SourceType
from app.pipeline import download
from app.pipeline.download import LinkError, build_embed_url, inspect_link

RUTUBE_ID = "0123456789abcdef0123456789abcdef"
DISK_URL = "https://disk.yandex.ru/i/AbCdEf"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
        ("https://m.youtube.com/shorts/dQw4w9WgXcQ", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
        (f"https://rutube.ru/video/{RUTUBE_ID}/", f"https://rutube.ru/play/embed/{RUTUBE_ID}"),
        (
            f"https://rutube.ru/video/private/{RUTUBE_ID}/?p=key1",
            f"https://rutube.ru/play/embed/{RUTUBE_ID}?p=key1",
        ),
        (
            "https://vkvideo.ru/video-12345_456239017",
            "https://vkvideo.ru/video_ext.php?oid=-12345&id=456239017",
        ),
        (
            "https://vk.com/video?z=video-12345_456239017%2Fpl_cat_trends",
            "https://vkvideo.ru/video_ext.php?oid=-12345&id=456239017",
        ),
        (
            "https://vk.com/video_ext.php?oid=-1&id=2&hash=abc",
            "https://vkvideo.ru/video_ext.php?oid=-1&id=2",
        ),
        ("https://youtube.com/watch?v=short", None),
        ("https://rutube.ru/channel/123/", None),
        ("https://files.lecturo.test/lecture.mp4", None),
    ],
)
def test_build_embed_url(url, expected):
    assert build_embed_url(url) == expected


@pytest.fixture
def public_host(monkeypatch):
    checked = []

    async def allow(url):
        checked.append(url)

    monkeypatch.setattr(download, "ensure_public_host", allow)
    return checked


def fake_info(monkeypatch, **info):
    monkeypatch.setattr(download, "extract_info", lambda url: info)


async def test_inspect_link_reads_title_and_duration(public_host, monkeypatch):
    fake_info(monkeypatch, title="Лекция 1", duration=3600)

    link = await inspect_link(f"https://rutube.ru/video/{RUTUBE_ID}/")

    assert link.title == "Лекция 1"
    assert link.duration == 3600.0
    assert link.embed_url == f"https://rutube.ru/play/embed/{RUTUBE_ID}"


async def test_inspect_link_rejects_longer_than_four_hours(public_host, monkeypatch):
    fake_info(monkeypatch, title="Марафон", duration=4 * 3600 + 1)

    with pytest.raises(LinkError, match="4 часов"):
        await inspect_link("https://vkvideo.ru/video-1_2")


async def test_inspect_link_probes_duration_of_direct_file(public_host, monkeypatch):
    fake_info(monkeypatch, title="lecture", url="https://files.lecturo.test/lecture.mp4")
    probed = []

    async def probe(url):
        probed.append(url)
        return 1800.5

    monkeypatch.setattr(download, "probe_duration", probe)

    link = await inspect_link("https://files.lecturo.test/lecture.mp4")

    assert link.duration == 1800.5
    assert link.embed_url is None
    assert probed == ["https://files.lecturo.test/lecture.mp4"]
    assert public_host == ["https://files.lecturo.test/lecture.mp4"] * 2


async def test_inspect_link_rejects_unknown_duration(public_host, monkeypatch):
    fake_info(monkeypatch, title="lecture")

    async def probe(url):
        return None

    monkeypatch.setattr(download, "probe_duration", probe)

    with pytest.raises(LinkError, match="длительность"):
        await inspect_link("https://files.lecturo.test/lecture.mp4")


async def test_inspect_link_rejects_live_and_playlists(public_host, monkeypatch):
    fake_info(monkeypatch, is_live=True, title="Эфир")
    with pytest.raises(LinkError, match="трансляции"):
        await inspect_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    fake_info(monkeypatch, _type="playlist", title="Курс")
    with pytest.raises(LinkError, match="плейлист"):
        await inspect_link("https://www.youtube.com/playlist?list=PL1")


async def test_ensure_public_host_rejects_internal_addresses():
    with pytest.raises(LinkError, match="внутреннюю сеть"):
        await download.ensure_public_host("http://127.0.0.1:6379/")


@pytest.mark.parametrize(
    ("media_url", "message"),
    [("http://10.0.0.5/lecture.mp4", "внутреннюю сеть"), ("file:///etc/passwd", "http и https")],
)
async def test_inspect_link_checks_media_url_before_probe(monkeypatch, media_url, message):
    fake_info(monkeypatch, title="lecture", url=media_url)
    probed = []

    async def probe(url):
        probed.append(url)
        return 60.0

    monkeypatch.setattr(download, "probe_duration", probe)

    with pytest.raises(LinkError, match=message):
        await inspect_link("http://93.184.216.34/lecture")
    assert probed == []


async def test_probe_duration_does_not_read_local_files(tmp_path):
    path = tmp_path / "lecture.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)

    assert await download.probe_duration(str(path)) is None
    assert await download.probe_duration(f"file:{path}") is None


async def test_download_step_rejects_internal_link():
    lecture = Lecture(
        id=uuid.uuid4(),
        title="Матанализ",
        source_type=SourceType.link,
        source_url="http://127.0.0.1:8000/lecture.mp4",
    )

    with pytest.raises(LinkError, match="внутреннюю сеть"):
        await download.download(None, lecture, None)


def disk_transport(meta: dict, requests: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        assert request.url.params["public_key"] == DISK_URL
        if request.url.path.endswith("/download"):
            return httpx.Response(200, json={"href": "https://downloader.disk.yandex.ru/x"})
        return httpx.Response(200, json=meta)

    return httpx.MockTransport(handler)


async def test_resolve_yandex_disk_returns_name_and_direct_link():
    requests = []
    transport = disk_transport(
        {"type": "file", "media_type": "video", "name": "Лекция 3.mp4"}, requests
    )

    name, href = await download.resolve_yandex_disk(DISK_URL, transport)

    assert name == "Лекция 3.mp4"
    assert href == "https://downloader.disk.yandex.ru/x"
    assert requests == ["/v1/disk/public/resources", "/v1/disk/public/resources/download"]


async def test_resolve_yandex_disk_rejects_folder():
    transport = disk_transport({"type": "dir", "name": "Лекции"}, [])

    with pytest.raises(LinkError, match="видео или аудиофайл"):
        await download.resolve_yandex_disk(DISK_URL, transport)


async def test_resolve_yandex_disk_rejects_closed_link():
    transport = httpx.MockTransport(lambda request: httpx.Response(404, json={}))

    with pytest.raises(LinkError, match="не найден"):
        await download.resolve_yandex_disk(DISK_URL, transport)


def no_network(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("нет сети", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        no_network,
        lambda request: httpx.Response(200, text="не json"),
        lambda request: httpx.Response(200, json={"type": "file", "media_type": "video"}),
    ],
    ids=["connect-error", "bad-json", "missing-field"],
)
async def test_resolve_yandex_disk_turns_api_failures_into_link_error(handler):
    with pytest.raises(LinkError, match="Яндекс Диск не ответил"):
        await download.resolve_yandex_disk(DISK_URL, httpx.MockTransport(handler))


async def test_inspect_link_for_yandex_disk(public_host, monkeypatch):
    transport = disk_transport({"type": "file", "media_type": "video", "name": "Лекция 3.mp4"}, [])
    monkeypatch.setattr(
        download,
        "resolve_yandex_disk",
        functools.partial(download.resolve_yandex_disk, transport=transport),
    )

    async def probe(url):
        assert url == "https://downloader.disk.yandex.ru/x"
        return 5400.0

    monkeypatch.setattr(download, "probe_duration", probe)

    link = await inspect_link(DISK_URL)

    assert link.title == "Лекция 3"
    assert link.duration == 5400.0
    assert link.embed_url is None


async def test_download_saves_audio_path(public_host, monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    download.get_settings.cache_clear()
    calls = []

    def fake_fetch(url, target, progress):
        calls.append(url)
        progress["fraction"] = 1.0
        return target.with_suffix(".opus")

    monkeypatch.setattr(download, "fetch_audio", fake_fetch)
    reported = []

    async def report(progress):
        reported.append(progress)

    lecture = Lecture(
        id=uuid.uuid4(),
        title="Матанализ",
        source_type=SourceType.link,
        source_url="https://vkvideo.ru/video-1_2",
    )
    try:
        await download.download(None, lecture, report)
    finally:
        download.get_settings.cache_clear()

    assert calls == ["https://vkvideo.ru/video-1_2"]
    assert public_host == ["https://vkvideo.ru/video-1_2"]
    assert lecture.audio_path == str(tmp_path / "audio" / f"{lecture.id}.opus")
    assert reported[-1] == 1.0


def test_link_requests_have_timeouts_and_limited_retries():
    assert download.BASE_OPTIONS["socket_timeout"] == 30
    assert download.BASE_OPTIONS["retries"] == 3
    assert download.BASE_OPTIONS["fragment_retries"] == 3


class FakeYoutubeDL:
    def __init__(self, options, creates_file):
        self.options = options
        self.creates_file = creates_file

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        if self.creates_file:
            Path(self.options["outtmpl"].replace("%(ext)s", "opus")).write_bytes(b"opus")


@pytest.mark.parametrize("creates_file", [True, False])
def test_fetch_audio_requires_downloaded_file(monkeypatch, tmp_path, creates_file):
    monkeypatch.setattr(download, "YoutubeDL", lambda options: FakeYoutubeDL(options, creates_file))
    target = tmp_path / "lecture"

    if creates_file:
        assert download.fetch_audio("https://vkvideo.ru/video-1_2", target, {}) == (
            tmp_path / "lecture.opus"
        )
    else:
        with pytest.raises(RuntimeError, match="не скачалось"):
            download.fetch_audio("https://vkvideo.ru/video-1_2", target, {})
