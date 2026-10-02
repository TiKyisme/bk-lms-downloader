from pathlib import Path
import json
import sys
import io
from contextlib import redirect_stderr, redirect_stdout

# Allow `python app.py` from a source checkout without installing the package.
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

if __name__ == "__main__":
    if "--diagnose-ai-course" in sys.argv:
        from bklms_downloader import __version__

        try:
            course_folder = Path(sys.argv[sys.argv.index("--diagnose-ai-course") + 1])
        except IndexError:
            raise SystemExit("--diagnose-ai-course requires a course folder")
        report_path = None
        if "--diagnose-ai-course-output" in sys.argv:
            try:
                report_path = Path(sys.argv[sys.argv.index("--diagnose-ai-course-output") + 1]).expanduser()
            except IndexError:
                raise SystemExit("--diagnose-ai-course-output requires an output filename")
        if sys.stdout is None and report_path is None:
            if sys.platform == "win32":
                import ctypes

                kernel32 = ctypes.windll.kernel32
                if not kernel32.AttachConsole(-1):
                    kernel32.AllocConsole()
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                from bklms_downloader.ai_prepare import run_ai_course_diagnostic

                diagnostic = run_ai_course_diagnostic(course_folder)
        except Exception as exc:
            diagnostic = {
                "app_version": __version__,
                "source_inventory": {},
                "resolved_root_status": "diagnostic_failed",
                "ready_source_count": 0,
                "chunk_count": 0,
                "retained_lecturer_source_count": 0,
                "source_error_count": 0,
                "unsupported_source_count": 0,
                "failed_relative_files": [],
                "failure_phase": "diagnostic",
                "failure_reason": type(exc).__name__,
            }
        rendered = json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n"
        if report_path is not None:
            try:
                with report_path.open("x", encoding="utf-8") as handle:
                    handle.write(rendered)
            except OSError:
                raise SystemExit("Could not create the requested diagnostic report.")
        else:
            print(rendered, end="")
        raise SystemExit(0 if diagnostic.get("meaningful_lecturer_source_count", 0) else 1)
    if "--diagnose-chrome" in sys.argv:
        from bklms_downloader.login_startup import diagnose_chrome

        raise SystemExit(diagnose_chrome())
    if "--validate-ai-pack" in sys.argv:
        from bklms_downloader.ai_study_pack import run_ai_study_pack_validator

        try:
            pack_path = Path(sys.argv[sys.argv.index("--validate-ai-pack") + 1])
        except IndexError:
            raise SystemExit("--validate-ai-pack requires a study-pack directory")
        raise SystemExit(run_ai_study_pack_validator(pack_path))
    if "--self-test-ai" in sys.argv:
        from bklms_downloader.ai_prepare import run_ai_runtime_self_test

        raise SystemExit(run_ai_runtime_self_test())
    if "--self-test-sync" in sys.argv:
        from bklms_downloader.sync_smoke import run_sync_runtime_self_test

        raise SystemExit(run_sync_runtime_self_test())
    if "--self-test-scroll" in sys.argv:
        from bklms_downloader.scroll_smoke import run_scroll_runtime_self_test

        raise SystemExit(run_scroll_runtime_self_test())
    if "--self-test-lite-runtime" in sys.argv:
        from bklms_downloader.lite_runtime import run_lite_runtime_self_test

        raise SystemExit(run_lite_runtime_self_test())
    if "--diagnose-ai" in sys.argv:
        from bklms_downloader.ai_prepare import run_ai_runtime_diagnostics

        raise SystemExit(run_ai_runtime_diagnostics())
    else:
        from bklms_downloader.gui import main

        main()
