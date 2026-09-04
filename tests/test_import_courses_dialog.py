from pathlib import Path
from types import SimpleNamespace

import pytest

from bklms_downloader.app_settings import AppSettings
from bklms_downloader.course_discovery import DiscoveredCourse
from bklms_downloader.course_store import CourseStore
from bklms_downloader.gui import App, ImportCoursesDialog, directory_picker_initial_dir


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def discovered(course_id: int, name: str = "Course") -> DiscoveredCourse:
    return DiscoveredCourse(
        url=f"https://lms.hcmut.edu.vn/course/view.php?id={course_id}",
        course_id=str(course_id),
        name=name,
        code="CO3001",
    )


def test_import_output_defaults_to_last_selected_folder(tmp_path: Path):
    parent = SimpleNamespace(settings=SimpleNamespace(last_output_dir=str(tmp_path)))
    assert ImportCoursesDialog.default_output(parent) == str(tmp_path)


def test_directory_picker_uses_existing_current_then_safe_fallback(tmp_path: Path):
    current = tmp_path / "current"
    fallback = tmp_path / "fallback"
    current.mkdir()
    fallback.mkdir()

    assert directory_picker_initial_dir(str(current), str(fallback), home=tmp_path) == current
    assert directory_picker_initial_dir(str(tmp_path / "missing"), str(fallback), home=tmp_path) == fallback
    assert directory_picker_initial_dir("", "", home=tmp_path) == tmp_path


def test_cancelled_folder_picker_changes_neither_field_nor_settings(monkeypatch, tmp_path: Path):
    dialog = ImportCoursesDialog.__new__(ImportCoursesDialog)
    dialog.output_var = FakeVar(str(tmp_path / "original"))
    dialog.parent_app = SimpleNamespace(
        settings=SimpleNamespace(default_output=str(tmp_path), last_output_dir="persisted")
    )
    monkeypatch.setattr("bklms_downloader.gui.filedialog.askdirectory", lambda **_kwargs: "")

    ImportCoursesDialog._choose_output(dialog)

    assert dialog.output_var.get() == str(tmp_path / "original")
    assert dialog.parent_app.settings.last_output_dir == "persisted"


def test_cancelled_import_closes_without_adding_courses():
    dialog = ImportCoursesDialog.__new__(ImportCoursesDialog)
    dialog.on_add = lambda *_args: pytest.fail("cancel must not add")
    dialog.destroy = lambda: setattr(dialog, "destroyed", True)

    ImportCoursesDialog._cancel(dialog)

    assert dialog.destroyed


def test_submit_uses_chosen_folder_and_excludes_existing_courses(monkeypatch, tmp_path: Path):
    new = discovered(1, "New")
    existing = discovered(2, "Existing")
    dialog = ImportCoursesDialog.__new__(ImportCoursesDialog)
    dialog.courses = [new, existing]
    dialog.available_urls = {new.url}
    dialog.selection_vars = {new.url: FakeVar(True), existing.url: FakeVar(True)}
    dialog.output_var = FakeVar(str(tmp_path / "chosen"))
    submitted = []
    dialog.on_add = lambda courses, output: submitted.append((courses, output))
    dialog.destroy = lambda: setattr(dialog, "destroyed", True)
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showwarning", lambda *_args, **_kwargs: pytest.fail("warning"))
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showerror", lambda *_args, **_kwargs: pytest.fail("error"))

    ImportCoursesDialog._submit(dialog)

    assert submitted == [([new], str(tmp_path / "chosen"))]
    assert dialog.destroyed


def test_submit_rejects_empty_output_and_keeps_dialog_open(monkeypatch):
    course = discovered(1)
    dialog = ImportCoursesDialog.__new__(ImportCoursesDialog)
    dialog.courses = [course]
    dialog.available_urls = {course.url}
    dialog.selection_vars = {course.url: FakeVar(True)}
    dialog.output_var = FakeVar("   ")
    dialog.on_add = lambda *_args: pytest.fail("must not add")
    dialog.destroy = lambda: pytest.fail("must remain open")
    warnings = []
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showwarning", lambda *args, **_kwargs: warnings.append(args))

    ImportCoursesDialog._submit(dialog)

    assert warnings and warnings[0][0] == "Thư mục lưu"


def test_submit_displays_persistence_error_and_keeps_dialog_open(monkeypatch, tmp_path: Path):
    course = discovered(1)
    dialog = ImportCoursesDialog.__new__(ImportCoursesDialog)
    dialog.courses = [course]
    dialog.available_urls = {course.url}
    dialog.selection_vars = {course.url: FakeVar(True)}
    dialog.output_var = FakeVar(str(tmp_path))
    dialog.on_add = lambda *_args: (_ for _ in ()).throw(OSError("disk full"))
    dialog.destroy = lambda: pytest.fail("must remain open")
    errors = []
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showerror", lambda *args, **_kwargs: errors.append(args))

    ImportCoursesDialog._submit(dialog)

    assert errors and "disk full" in errors[0][1]


def test_confirmed_import_batches_one_write_preserves_existing_output_and_persists_choice(
    monkeypatch,
    tmp_path: Path,
):
    store = CourseStore(tmp_path / "courses.json")
    old_output = tmp_path / "old"
    existing = store.add(discovered(1).url, old_output, name="Existing")
    settings = AppSettings(tmp_path / "settings.json", default_output=tmp_path / "default")
    app = App.__new__(App)
    app.store = store
    app.settings = settings
    saves = 0
    original_save = store.save

    def count_save():
        nonlocal saves
        saves += 1
        original_save()

    monkeypatch.setattr(store, "save", count_save)
    chosen = tmp_path / "chosen"
    added = App._persist_imported_courses(
        app,
        [discovered(1, "Duplicate"), discovered(2, "New two"), discovered(2, "Duplicate two")],
        str(chosen),
    )

    assert len(added) == 1
    assert saves == 1
    assert store.get(existing.id).output == str(old_output)
    assert added[0].output == str(chosen)
    assert AppSettings(settings.path).last_output_dir == str(chosen)


def test_import_course_failure_rolls_back_persisted_default(tmp_path: Path):
    old_output = tmp_path / "old"
    settings = AppSettings(tmp_path / "settings.json", default_output=old_output)
    settings.set_last_output_dir(old_output)
    app = App.__new__(App)
    app.settings = settings
    app.store = SimpleNamespace(add_many=lambda _entries: (_ for _ in ()).throw(OSError("write failed")))

    with pytest.raises(OSError, match="write failed"):
        App._persist_imported_courses(app, [discovered(1)], str(tmp_path / "new"))

    assert settings.last_output_dir == str(old_output)
    assert AppSettings(settings.path).last_output_dir == str(old_output)


def test_settings_failure_prevents_course_persistence(tmp_path: Path):
    store_calls = []
    app = App.__new__(App)
    app.settings = SimpleNamespace(
        last_output_dir=str(tmp_path / "old"),
        set_last_output_dir=lambda _output: (_ for _ in ()).throw(OSError("settings read-only")),
    )
    app.store = SimpleNamespace(add_many=lambda entries: store_calls.append(list(entries)))

    with pytest.raises(OSError, match="settings read-only"):
        App._persist_imported_courses(app, [discovered(1)], str(tmp_path / "new"))

    assert store_calls == []


def test_settings_failure_prevents_course_persistence(tmp_path: Path):
    app = App.__new__(App)

    class Settings:
        last_output_dir = str(tmp_path / "old")

        def set_last_output_dir(self, _output):
            raise OSError("settings read only")

    class Store:
        def add_many(self, _entries):
            pytest.fail("courses must not be added when settings persistence fails")

    app.settings = Settings()
    app.store = Store()

    with pytest.raises(OSError, match="settings read only"):
        App._persist_imported_courses(app, [discovered(1)], str(tmp_path / "new"))
