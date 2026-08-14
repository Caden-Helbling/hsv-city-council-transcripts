"""Shared test fakes: a URL-routing fake requests.Session."""
from typing import Any

ARCHIVE_HTML = '<a href="https://www.huntsvilleal.gov/videos/huntsville-city-council-meeting-june-25-2026-2/">x</a>'
VIDEO_HTML = ('<h1 class="full-width-headline">Huntsville City Council Meeting &#8211; June 25, 2026</h1>'
              '<iframe src="https://cloud.castus.tv/vod/hsv-tv/embed/6a3dcff79537260002c64cd9"></iframe>')
LEGISTAR_EVENTS = [{
    "EventId": 1223, "EventDate": "2026-06-25T00:00:00",
    "EventBodyName": "City Council Regular Meeting",
    "EventAgendaFile": "https://legistar/agenda.pdf", "EventMinutesFile": None,
    "EventInSiteURL": "https://huntsvilleal.legistar.com/MeetingDetail.aspx?LEGID=1223",
}]


class FakeResponse:
    def __init__(self, *, text: str = "", payload: Any = None, content: bytes = b"",
                 status: int = 200) -> None:
        self.text, self._payload, self.content, self.status_code = text, payload, content, status

    def json(self) -> Any:
        return self._payload

    def iter_content(self, chunk_size: int) -> Any:
        yield self.content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *a: Any) -> None:
        pass


class FakeSession:
    """Routes by URL substring; records call URLs."""

    def __init__(self, video_status: int = 200) -> None:
        self.calls: list[str] = []
        self.video_status = video_status

    def get(self, url: str, params: Any = None, timeout: int = 0, stream: bool = False) -> FakeResponse:
        self.calls.append(url)
        if "videocategory" in url and "page/2" in url:
            return FakeResponse(status=404)
        if "videocategory" in url:
            return FakeResponse(text=ARCHIVE_HTML)
        if "/videos/" in url:
            return FakeResponse(text=VIDEO_HTML, status=self.video_status)
        if "webapi.legistar.com" in url:
            return FakeResponse(payload=LEGISTAR_EVENTS)
        if url.endswith(".pdf"):
            return FakeResponse(content=b"%PDF-fake")
        if ".vtt" in url:
            return FakeResponse(text="WEBVTT\n\n00:01:00.000 --> 00:01:01.000\nHello.\n")
        if url.endswith(".mp4"):
            return FakeResponse(content=b"video")
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, json: Any = None, timeout: int = 0) -> FakeResponse:
        self.calls.append(url)
        if url.endswith("/upload/get"):
            return FakeResponse(payload={"response": {"payload": {"data": "https://cdn/out_1080.mp4?sig"}}})
        if url.endswith("/upload/get-captions"):
            return FakeResponse(payload={"response": {"payload": "https://s3/cap.vtt?sig"}})
        raise AssertionError(f"unexpected POST {url}")
