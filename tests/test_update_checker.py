import requests

from bklms_downloader.update_checker import UpdateChecker, is_newer_version, parse_version


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("request failed")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def release(tag, **extra):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/TiKyisme/bk-lms-downloader/releases/tag/{tag}",
        "body": "Release notes",
        "assets": [{"name": "BK-LMS-Downloader.exe", "browser_download_url": "https://example.test/app.exe"}],
        **extra,
    }


def test_semantic_version_comparison():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2") is None
    assert parse_version("v1.2.3-rc1") is None
    assert is_newer_version("v1.10.0", "1.9.9")
    assert not is_newer_version("1.0.0", "1.0.0")


def test_no_update_for_current_or_older_release():
    checker = UpdateChecker("0.4.0", session=FakeSession(FakeResponse([release("v0.4.0")])))
    assert checker.check() is None

    checker = UpdateChecker("0.4.0", session=FakeSession(FakeResponse([release("v0.3.9")])))
    assert checker.check() is None


def test_newer_stable_release_returns_structured_update():
    checker = UpdateChecker("0.4.0", session=FakeSession(FakeResponse([release("v0.4.1")])))

    update = checker.check()

    assert update is not None
    assert update.latest_version == "0.4.1"
    assert update.update_available
    assert update.download_url == "https://example.test/app.exe"


def test_prerelease_and_malformed_releases_are_ignored():
    payload = [
        release("v9.0.0", prerelease=True),
        release("nightly"),
        release("v0.4.1", draft=True),
        release("v0.4.0"),
    ]
    assert UpdateChecker("0.4.0", session=FakeSession(FakeResponse(payload))).check() is None


def test_malformed_and_network_failures_are_safe():
    assert UpdateChecker("0.4.0", session=FakeSession(FakeResponse({}))).check() is None
    assert UpdateChecker("0.4.0", session=FakeSession(FakeResponse(ValueError("bad json")))).check() is None
    assert UpdateChecker("0.4.0", session=FakeSession(error=requests.Timeout())).check() is None
