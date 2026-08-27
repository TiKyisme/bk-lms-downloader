from pathlib import Path
import sys

# Allow `python app.py` from a source checkout without installing the package.
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from bklms_downloader.gui import main

if __name__ == "__main__":
    if "--validate-ai-pack" in sys.argv:
        from bklms_downloader.ai_study_pack import run_ai_study_pack_validator

        try:
            pack_path = Path(sys.argv[sys.argv.index("--validate-ai-pack") + 1])
        except IndexError:
            raise SystemExit("--validate-ai-pack requires an AI_Knowledge path")
        raise SystemExit(run_ai_study_pack_validator(pack_path))
    if "--self-test-ai" in sys.argv:
        from bklms_downloader.ai_prepare import run_ai_runtime_self_test

        raise SystemExit(run_ai_runtime_self_test())
    if "--diagnose-ai" in sys.argv:
        from bklms_downloader.ai_prepare import run_ai_runtime_diagnostics

        raise SystemExit(run_ai_runtime_diagnostics())
    else:
        main()
