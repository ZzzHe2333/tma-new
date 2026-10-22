import os
from pathlib import Path
import sys

# A windowed Windows executable has no console streams. Some scientific
# dependencies write import diagnostics even before the Qt application starts.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    try:
        log_folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ZzzHeTMA" / "logs"
        log_folder.mkdir(parents=True, exist_ok=True)
        sys.stderr = (log_folder / "runtime.log").open("a", encoding="utf-8")
    except OSError:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

from tma_app.app import main

if __name__ == "__main__":
    main()
