import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import NoSuchWindowException, WebDriverException

from bklms_downloader import auth, login_startup
from bklms_downloader.gui import App
from bklms_downloader.login_startup import LoginStartup


def driver():
    return SimpleNamespace(
        window_handles=["owned"], switch_to=SimpleNamespace(window=Mock()),
        get=Mock(), quit=Mock(),
    )


def test_browser_ready_precedes_navigation_and_no_fixed_wait(monkeypatch):
    browser = driver()
    events = []
    monkeypatch.setattr(login_startup, "create_driver", lambda **kw: browser)
    monkeypatch.setattr(auth, "wait_page", lambda *a, **k: pytest.fail("redundant wait"))
    browser.get.side_effect = lambda url: events.append({"event": "navigation"})
    startup = LoginStartup()
    startup.run(events.append, time.perf_counter())
    assert [e["event"] for e in events] == [
        "login_ready", "navigation", "login_navigation_complete", "login_finished"
    ]
    assert startup.driver is browser


def test_healthy_driver_is_reused(monkeypatch):
    startup = LoginStartup()
    startup.driver = driver()
    monkeypatch.setattr(login_startup, "create_driver", lambda **kw: pytest.fail("duplicate"))
    startup.run(lambda e: None, time.perf_counter())
    startup.driver.switch_to.window.assert_called_once_with("owned")
    startup.driver.get.assert_called_once()


def test_dead_driver_is_closed_and_recreated(monkeypatch):
    startup = LoginStartup()
    dead = driver()
    dead.window_handles = []
    startup.driver = dead
    fresh = driver()
    factory = Mock(return_value=fresh)
    monkeypatch.setattr(login_startup, "create_driver", factory)
    startup.run(lambda e: None, time.perf_counter())
    dead.quit.assert_called_once()
    assert startup.driver is fresh
    factory.assert_called_once()


def test_navigation_failure_retains_browser_and_redacts_exception(monkeypatch):
    startup = LoginStartup()
    startup.driver = driver()
    startup.driver.get.side_effect = WebDriverException("Cookie: private; secret URL")
    events = []
    logs = []
    monkeypatch.setattr(login_startup.LOG, "warning", lambda *args: logs.append(args))
    startup.run(events.append, time.perf_counter())
    assert startup.driver is not None
    assert [e["event"] for e in events] == ["login_ready", "login_error", "login_finished"]
    assert "private" not in str(events) + str(logs)
    assert "secret URL" not in str(events) + str(logs)


def test_shutdown_during_constructor_closes_only_created_driver(monkeypatch):
    startup = LoginStartup()
    browser = driver()
    def construct(**kwargs):
        startup.closing.set()
        return browser
    monkeypatch.setattr(login_startup, "create_driver", construct)
    events = []
    startup.run(events.append, time.perf_counter())
    browser.quit.assert_called_once()
    browser.get.assert_not_called()
    assert startup.driver is None


def test_closed_immediately_is_reported_and_cleaned(monkeypatch):
    startup = LoginStartup()
    browser = driver()
    browser.window_handles = []
    monkeypatch.setattr(login_startup, "create_driver", lambda **k: browser)
    events = []
    startup.run(events.append, time.perf_counter())
    assert events[0]["event"] == "login_error"
    assert "đã đóng" in events[0]["message"]
    browser.quit.assert_called_once()


def test_create_driver_eager_resolves_once_and_logs_numeric_timings(monkeypatch, tmp_path):
    binary = tmp_path / "browser"
    binary.touch()
    service = SimpleNamespace(path=None)
    monkeypatch.setattr(auth, "Service", lambda: service)
    resolver = Mock(return_value={"browser_path": str(binary), "driver_path": str(binary)})
    monkeypatch.setattr(auth, "SeleniumManager", lambda: SimpleNamespace(binary_paths=resolver))
    browser = Mock()
    constructor = Mock(return_value=browser)
    monkeypatch.setattr(auth.webdriver, "Chrome", constructor)
    timings = []
    assert auth.create_driver(lambda name, seconds: timings.append((name, seconds))) is browser
    assert constructor.call_args.kwargs["options"].page_load_strategy == "eager"
    assert service.path == str(binary)
    resolver.assert_called_once_with(["--browser", "chrome", "--avoid-stats"])
    assert [name for name, _ in timings] == ["options", "driver_resolution", "driver_create"]
    assert all(isinstance(value, float) for _, value in timings)


def test_discovery_readiness_is_still_explicit(monkeypatch):
    # Real helper still polls DOM when invoked by discovery/sync.
    wait = Mock()
    monkeypatch.setattr(auth, "WebDriverWait", lambda d, timeout: wait)
    monkeypatch.setattr(auth.time, "sleep", lambda seconds: None)
    auth.wait_page(driver(), extra=0.1)
    predicate = wait.until.call_args.args[0]
    assert predicate(SimpleNamespace(execute_script=lambda js: "interactive"))
    assert not predicate(SimpleNamespace(execute_script=lambda js: "loading"))


def bare_app():
    app = App.__new__(App)
    app.syncing = False
    app.login_opening = False
    app.driver = None
    app._login_startup = LoginStartup()
    app.events = queue.Queue()
    app._set_login_status = Mock()
    app.current_course_var = SimpleNamespace(set=Mock())
    for name in ("login_btn", "import_btn", "sync_selected_btn", "sync_all_btn"):
        setattr(app, name, SimpleNamespace(configure=Mock()))
    return app


def test_click_returns_while_worker_blocked_and_double_click_cannot_spawn(monkeypatch):
    app = bare_app()
    entered, release = threading.Event(), threading.Event()
    browser = driver()
    creations = []
    def construct(**kwargs):
        creations.append(1)
        entered.set()
        assert release.wait(5)
        return browser
    monkeypatch.setattr(login_startup, "create_driver", construct)
    try:
        App._open_login(app)
        assert entered.wait(5)  # Constructor is still blocked, but Tk handler returned.
        App._open_login(app)
        assert creations == [1]
    finally:
        release.set()
    # Wait on the worker's terminal event rather than a fixed sleep.
    while app.events.get(timeout=5)["event"] != "login_finished":
        pass
    assert app.driver is browser
    App._handle_event(app, {"event": "login_finished"})
    assert not app.login_opening
    app.login_btn.configure.assert_called_with(state="normal")


def test_failure_terminal_event_restores_controls(monkeypatch):
    app = bare_app()
    app.login_opening = True
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showerror", Mock())
    App._handle_event(app, {"event": "login_error", "message": "Không khởi động được Chrome."})
    App._handle_event(app, {"event": "login_finished"})
    assert not app.login_opening
    for name in ("login_btn", "import_btn", "sync_selected_btn", "sync_all_btn"):
        getattr(app, name).configure.assert_called_with(state="normal")


def test_constructor_failure_always_delivers_finish_and_safe_message(monkeypatch):
    startup = LoginStartup()
    def fail(**kwargs):
        raise WebDriverException("cannot find chrome binary; Cookie: do-not-log")
    monkeypatch.setattr(login_startup, "create_driver", fail)
    events = []
    startup.run(events.append, time.perf_counter())
    assert startup.driver is None
    assert [event["event"] for event in events] == ["login_error", "login_finished"]
    assert "Không tìm thấy Google Chrome" in events[0]["message"]
    assert "do-not-log" not in str(events)
