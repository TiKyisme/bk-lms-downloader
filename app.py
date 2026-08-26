from pathlib import Path
import sys

# Allow `python app.py` from a source checkout without installing the package.
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from bklms_downloader.gui import main

if __name__ == "__main__":
    main()
