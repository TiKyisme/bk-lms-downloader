from types import SimpleNamespace

from bklms_downloader import __version__
from bklms_downloader.gui import App


def test_onboarding_targets_are_actual_controls():
    app = App.__new__(App)
    app.login_btn = object()
    app.import_btn = object()
    app.course_scroll = object()
    app.sync_selected_btn = object()
    app.tools_btn = object()

    assert App._onboarding_target(app, "login") is app.login_btn
    assert App._onboarding_target(app, "import") is app.import_btn
    assert App._onboarding_target(app, "courses") is app.course_scroll
    assert App._onboarding_target(app, "sync") is app.sync_selected_btn
    assert App._onboarding_target(app, "tools") is app.tools_btn
    assert App._onboarding_target(app, None) is None


def test_feedback_dialog_is_available_without_login(monkeypatch):
    created = []
    app = App.__new__(App)
    app.driver = None

    def fake_dialog(parent, **kwargs):
        created.append((parent, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr("bklms_downloader.gui.FeedbackDialog", fake_dialog)
    monkeypatch.setattr("bklms_downloader.gui.current_platform_label", lambda: "Windows 11")

    App._show_feedback_dialog(app)

    assert created[0][0] is app
    assert created[0][1]["app_version"] == __version__
    assert created[0][1]["platform"] == "Windows 11"
