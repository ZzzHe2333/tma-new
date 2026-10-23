import os
from pathlib import Path
import sys

from tma_app.diagnostics import install as install_diagnostics
install_diagnostics()

from tma_app.ui_size import configure_environment
configure_environment()

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

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--verify-cloud-schedule":
        from tma_app.cloud_qa import verify_scheduled_cleanup
        sys.exit(0 if verify_scheduled_cleanup(sys.argv[2])["status"] == "passed" else 1)
    elif "--cloud-cleanup" in sys.argv:
        if "--cloud-config-folder" in sys.argv:
            index = sys.argv.index("--cloud-config-folder")
            folder = Path(sys.argv[index + 1]).resolve()
            if folder.name != "ZzzHeTMA":
                raise ValueError("云缓存配置目录名称必须为 ZzzHeTMA")
            os.environ["LOCALAPPDATA"] = str(folder.parent)
        from tma_app.cloud_storage import cleanup_main
        sys.exit(cleanup_main())
    else:
        # PyInstaller otherwise recreates the font catalogue on every launch.
        # Configure before app.py imports any Matplotlib module.
        from tma_app.startup_cache import configure as configure_plot_cache
        configure_plot_cache()
        from tma_app.app import main
        main()
