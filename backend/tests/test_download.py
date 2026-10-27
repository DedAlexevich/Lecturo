import functools
import threading
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.models import Lecture, SourceType
from app.pipeline import download, media
from app.pipeline.download import (
    LinkError,
    build_embed_url,
    inspect_link,
    link_key,
    with_scheme,
    yandex_disk_resource,
)

RUTUBE_ID = "0123456789abcdef0123456789abcdef"
DISK_URL = "https://disk.yandex.ru/i/AbCdEf"
DISK_FOLDER_FILE_URL = (
    "https://disk.yandex.ru/d/JdCCuy4h8fR75A/"
    "%D0%9B%D0%B5%D0%BA%D1%86%D0%B8%D1%8F%2003%202025-09-10%2010-20-00.mp4"
)


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
            "https://vk.com/video_ext.php?oid=-1&id=2&hash=abc&hd=2",
            "https://vkvideo.ru/video_ext.php?oid=-1&id=2&hash=abc",
        ),
        (
            "https://vk.com/video_ext.php?oid=-1&id=2",
            "https://vkvideo.ru/video_ext.php?oid=-1&id=2",
        ),
        ("https://youtube.com/watch?v=short", None),
        ("https://rutube.ru/channel/123/", None),
        ("https://files.lecturo.test/lecture.mp4", None),
    ],
)
def test_build_embed_url(url, expected):
    assert build_embed_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("disk.yandex.ru/d/AbCdEf", "https://disk.yandex.ru/d/AbCdEf"),
        ("  youtu.be/dQw4w9WgXcQ ", "https://youtu.be/dQw4w9WgXcQ"),
        ("www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("//rutube.ru/video/1/", "https://rutube.ru/video/1/"),
        ("http://vk.com/video-1_2", "http://vk.com/video-1_2"),
        ("https://vk.com/video-1_2", "https://vk.com/video-1_2"),
    ],
)
def test_with_scheme(url, expected):
    assert with_scheme(url) == expected


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        (
            [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://youtu.be/dQw4w9WgXcQ?si=abc&t=10",
                "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
                "https://youtube.com/shorts/dQw4w9WgXcQ",
                "youtube.com/watch?t=5&v=dQw4w9WgXcQ",
            ],
            "youtube:dQw4w9WgXcQ",
        ),
        (
            [
                f"https://rutube.ru/video/{RUTUBE_ID}/",
                f"https://rutube.ru/video/{RUTUBE_ID}/?r=wd",
                f"https://rutube.ru/play/embed/{RUTUBE_ID}",
            ],
            f"rutube:{RUTUBE_ID}",
        ),
        (
            [
                "https://vkvideo.ru/video-12345_456239017",
                "https://vk.com/video?z=video-12345_456239017%2Fpl_cat_trends",
                "https://vk.com/video_ext.php?oid=-12345&id=456239017&hash=abc",
            ],
            "vk:-12345_456239017",
        ),
        (
            [
                "https://Files.Lecturo.test/lecture.mp4",
                "https://files.lecturo.test/lecture.mp4/",
                "http://www.files.lecturo.test/lecture.mp4#start",
            ],
            "files.lecturo.test/lecture.mp4",
        ),
        (
            [
                DISK_FOLDER_FILE_URL,
                "disk.yandex.ru/d/JdCCuy4h8fR75A/Лекция 03 2025-09-10 10-20-00.mp4",
            ],
            "disk.yandex.ru/d/JdCCuy4h8fR75A/Лекция 03 2025-09-10 10-20-00.mp4",
        ),
    ],
)
def test_link_key_matches_forms_of_one_link(urls, expected):
    assert {link_key(url) for url in urls} == {expected}


def test_link_key_separates_different_videos():
    assert link_key("https://youtu.be/dQw4w9WgXcQ") != link_key("https://youtu.be/aaaaaaaaaaa")
    assert link_key("https://disk.yandex.ru/d/Key/a.mp4") != link_key(
        "https://disk.yandex.ru/d/Key/b.mp4"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (DISK_URL, (DISK_URL, None)),
        ("https://disk.yandex.ru/d/AbCdEf", ("https://disk.yandex.ru/d/AbCdEf", None)),
        ("https://disk.yandex.ru/d/AbCdEf/", ("https://disk.yandex.ru/d/AbCdEf/", None)),
        (
            DISK_FOLDER_FILE_URL,
            (
                "https://disk.yandex.ru/d/JdCCuy4h8fR75A",
                "/Лекция 03 2025-09-10 10-20-00.mp4",
            ),
        ),
        (
            "https://disk.yandex.ru/d/AbCdEf/Курс/Лекция%201.mp4?x=1",
            ("https://disk.yandex.ru/d/AbCdEf", "/Курс/Лекция 1.mp4"),
        ),
    ],
)
def test_yandex_disk_resource(url, expected):
    assert yandex_disk_resource(url) == expected


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

    async def follow(url):
        return "https://cdn.lecturo.test/lecture.mp4"

    monkeypatch.setattr(download, "probe_duration", probe)
    monkeypatch.setattr(download, "follow_redirects", follow)

    link = await inspect_link("https://files.lecturo.test/lecture.mp4")

    assert link.duration == 1800.5
    assert link.embed_url is None
    assert probed == ["https://cdn.lecturo.test/lecture.mp4"]
    assert public_host == ["https://files.lecturo.test/lecture.mp4"]


async def test_inspect_link_rejects_unknown_duration(public_host, monkeypatch):
    fake_info(monkeypatch, title="lecture")

    async def probe(url):
        return None

    async def follow(url):
        return url

    monkeypatch.setattr(download, "probe_duration", probe)
    monkeypatch.setattr(download, "follow_redirects", follow)

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


async def test_resolve_yandex_disk_passes_path_inside_folder():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(dict(request.url.params))
        if request.url.path.endswith("/download"):
            return httpx.Response(200, json={"href": "https://downloader.disk.yandex.ru/x"})
        return httpx.Response(
            200, json={"type": "file", "media_type": "video", "name": "Лекция 03.mp4"}
        )

    name, href = await download.resolve_yandex_disk(
        DISK_FOLDER_FILE_URL, httpx.MockTransport(handler)
    )

    assert (name, href) == ("Лекция 03.mp4", "https://downloader.disk.yandex.ru/x")
    expected = {
        "public_key": "https://disk.yandex.ru/d/JdCCuy4h8fR75A",
        "path": "/Лекция 03 2025-09-10 10-20-00.mp4",
    }
    assert requests == [expected, expected]


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

    async def follow(url):
        return url

    monkeypatch.setattr(download, "probe_duration", probe)
    monkeypatch.setattr(download, "follow_redirects", follow)

    link = await inspect_link(DISK_URL)

    assert link.title == "Лекция 3"
    assert link.duration == 5400.0
    assert link.embed_url is None


@pytest.fixture
def probed_duration(monkeypatch):
    durations = [1800.0]

    async def probe(path):
        return durations[0]

    monkeypatch.setattr(media, "probe_duration", probe)
    return durations


async def test_download_saves_audio_path(public_host, probed_duration, monkeypatch, tmp_path):
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


def link_lecture(duration: float | None = None) -> Lecture:
    return Lecture(
        id=uuid.uuid4(),
        title="Матанализ",
        source_type=SourceType.link,
        source_url="https://vkvideo.ru/video-1_2",
        duration_sec=duration,
    )


async def no_report(progress):
    pass


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    download.get_settings.cache_clear()
    yield tmp_path
    download.get_settings.cache_clear()


def fetch_file(url, target, progress):
    path = target.with_suffix(".opus")
    path.write_bytes(b"opus")
    return path


async def test_download_removes_partial_files_on_error(public_host, monkeypatch, storage):
    def failing_fetch(url, target, progress):
        target.with_suffix(".webm.part").write_bytes(b"part")
        raise LinkError("Файл по ссылке больше 2 ГБ")

    monkeypatch.setattr(download, "fetch_audio", failing_fetch)

    with pytest.raises(LinkError, match="2 ГБ"):
        await download.download(None, link_lecture(), no_report)

    assert not list((storage / "audio").iterdir())


def test_link_requests_have_timeouts_and_limited_retries():
    assert download.BASE_OPTIONS["socket_timeout"] == 30
    assert download.BASE_OPTIONS["retries"] == 3
    assert download.BASE_OPTIONS["fragment_retries"] == 3


class FakeYoutubeDL:
    def __init__(self, options, creates_file, statuses=()):
        self.options = options
        self.creates_file = creates_file
        self.statuses = statuses

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        for status in self.statuses:
            for hook in self.options["progress_hooks"]:
                hook(status)
        if self.creates_file:
            Path(self.options["outtmpl"].replace("%(ext)s", "opus")).write_bytes(b"opus")


@pytest.mark.parametrize("creates_file", [True, False])
def test_fetch_audio_requires_downloaded_file(monkeypatch, tmp_path, creates_file):
    monkeypatch.setattr(
        download, "PublicYoutubeDL", lambda options: FakeYoutubeDL(options, creates_file)
    )
    target = tmp_path / "lecture"

    if creates_file:
        assert download.fetch_audio("https://vkvideo.ru/video-1_2", target, {}) == (
            tmp_path / "lecture.opus"
        )
    else:
        with pytest.raises(RuntimeError, match="не скачалось"):
            download.fetch_audio("https://vkvideo.ru/video-1_2", target, {})


@pytest.fixture
def youtube_proxy(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PROXY", "socks5h://user:secret@proxy.test:1080")
    download.get_settings.cache_clear()
    yield "socks5h://user:secret@proxy.test:1080"
    download.get_settings.cache_clear()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_youtube_goes_through_proxy(youtube_proxy, url):
    assert download.ydl_options(url)["proxy"] == youtube_proxy


@pytest.mark.parametrize(
    "url",
    [
        f"https://rutube.ru/video/{RUTUBE_ID}/",
        "https://vkvideo.ru/video-12345_456239017",
        "https://files.lecturo.test/lecture.mp4",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_other_sources_skip_proxy(youtube_proxy, url):
    assert "proxy" not in download.ydl_options(url)


def test_no_proxy_without_setting(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PROXY", "")
    download.get_settings.cache_clear()
    try:
        assert download.ydl_options("https://youtu.be/dQw4w9WgXcQ") == download.BASE_OPTIONS
    finally:
        download.get_settings.cache_clear()


def test_fetch_audio_uses_proxy_for_youtube(monkeypatch, tmp_path, youtube_proxy):
    used = []

    def fake_ydl(options):
        used.append(options)
        return FakeYoutubeDL(options, True)

    monkeypatch.setattr(download, "PublicYoutubeDL", fake_ydl)
    download.fetch_audio("https://youtu.be/dQw4w9WgXcQ", tmp_path / "lecture", {})

    assert used[0]["proxy"] == youtube_proxy
    assert used[0]["format"].endswith("/bestaudio/best")


@pytest.mark.parametrize(
    "status",
    [
        {"status": "downloading", "downloaded_bytes": 1024, "total_bytes": 3 * 1024**3},
        {"status": "downloading", "downloaded_bytes": 2 * 1024**3 + 1},
    ],
    ids=["known-size", "unknown-size"],
)
def test_fetch_audio_stops_on_too_large_file(monkeypatch, tmp_path, status):
    monkeypatch.setattr(
        download, "PublicYoutubeDL", lambda options: FakeYoutubeDL(options, True, [status])
    )

    with pytest.raises(LinkError, match="больше 2 ГБ"):
        download.fetch_audio("https://vkvideo.ru/video-1_2", tmp_path / "lecture", {})


def test_fetch_audio_stops_on_slow_download(monkeypatch, tmp_path):
    status = {"status": "downloading", "downloaded_bytes": 1024, "total_bytes": 4096}
    monkeypatch.setattr(download, "DOWNLOAD_TIMEOUT_SEC", -1.0)
    monkeypatch.setattr(
        download, "PublicYoutubeDL", lambda options: FakeYoutubeDL(options, True, [status])
    )

    with pytest.raises(LinkError, match="больше часа"):
        download.fetch_audio("https://vkvideo.ru/video-1_2", tmp_path / "lecture", {})


def write_wav(path: Path, seconds: int = 1) -> Path:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return path


def serve(host: str, routes: dict[str, tuple[int, dict[str, str], bytes]]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for name, value in {**headers, "Content-Length": str(len(body))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def media_hosts(monkeypatch, tmp_path):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    wav = write_wav(tmp_path / "lecture.wav", seconds=2).read_bytes()
    internal = serve("127.0.0.1", {"/lecture.wav": (200, {"Content-Type": "audio/wav"}, wav)})
    internal_url = f"http://127.0.0.1:{internal.server_port}/lecture.wav"
    public = serve(
        "127.0.0.2",
        {
            "/lecture.wav": (200, {"Content-Type": "audio/wav"}, wav),
            "/to-loopback": (302, {"Location": internal_url}, b""),
            "/to-private": (302, {"Location": "http://10.0.0.5/lecture.wav"}, b""),
        },
    )
    monkeypatch.setattr(download, "is_public_ip", lambda address: address == "127.0.0.2")
    yield f"http://127.0.0.2:{public.server_port}"
    for server in (internal, public):
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("path", ["/to-loopback", "/to-private"])
async def test_inspect_link_rejects_redirect_to_internal_network(media_hosts, path):
    with pytest.raises(LinkError, match="внутреннюю сеть"):
        await inspect_link(media_hosts + path)


@pytest.mark.parametrize("path", ["/to-loopback", "/to-private"])
async def test_download_rejects_redirect_to_internal_network(media_hosts, storage, path):
    lecture = link_lecture()
    lecture.source_url = media_hosts + path

    with pytest.raises(LinkError, match="внутреннюю сеть"):
        await download.download(None, lecture, no_report)

    assert not list((storage / "audio").iterdir())


async def test_download_fetches_public_file(media_hosts, storage):
    lecture = link_lecture()
    lecture.source_url = media_hosts + "/lecture.wav"

    await download.download(None, lecture, no_report)

    assert lecture.audio_path == str(storage / "audio" / f"{lecture.id}.opus")


def test_real_download_stops_on_size_limit(media_hosts, monkeypatch, tmp_path):
    monkeypatch.setattr(download, "MAX_DOWNLOAD_BYTES", 4096)

    with pytest.raises(LinkError, match="больше 2 ГБ"):
        download.fetch_audio(media_hosts + "/lecture.wav", tmp_path / "downloaded", {})


def redirect_transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: routes[str(request.url)])


async def test_follow_redirects_returns_final_public_url():
    transport = redirect_transport(
        {
            "http://93.184.216.34/a": httpx.Response(302, headers={"Location": "/b"}),
            "http://93.184.216.34/b": httpx.Response(200),
        }
    )

    assert await download.follow_redirects("http://93.184.216.34/a", transport) == (
        "http://93.184.216.34/b"
    )


async def test_follow_redirects_rejects_internal_target():
    transport = redirect_transport(
        {
            "http://93.184.216.34/a": httpx.Response(
                302, headers={"Location": "http://10.0.0.5/lecture.mp4"}
            ),
        }
    )

    with pytest.raises(LinkError, match="внутреннюю сеть"):
        await download.follow_redirects("http://93.184.216.34/a", transport)


async def test_follow_redirects_limits_chain():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "/again"})
    )

    with pytest.raises(LinkError, match="перенаправлений"):
        await download.follow_redirects("http://93.184.216.34/a", transport)
