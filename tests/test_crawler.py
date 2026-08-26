from pathlib import Path

import requests

from bklms_downloader.crawler import DeepDownloader


def make_response(url: str, content_type: str, body: bytes = b"payload") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.headers["Content-Type"] = content_type
    response.headers["Content-Length"] = str(len(body))
    response._content = body
    response._content_consumed = True
    return response


def test_video_response_is_always_skipped(tmp_path: Path):
    downloader = DeepDownloader(
        session=requests.Session(),
        output=tmp_path,
        force=False,
        max_depth=4,
        follow_linked_courses=True,
    )
    response = make_response(
        "https://lms.hcmut.edu.vn/pluginfile.php/1/x/lecture.mp4",
        "video/mp4",
    )

    result = downloader.save_response_file(
        response=response,
        dest_dir=tmp_path,
        fallback="lecture.mp4",
        source=response.url,
        context="test",
    )

    assert result is None
    assert downloader.stats["skipped_video"] == 1
    assert list(tmp_path.iterdir()) == []
