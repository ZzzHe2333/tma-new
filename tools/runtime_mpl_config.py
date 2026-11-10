"""Keep PyInstaller's normal plot cache isolation out of directory-only workers.

The standard matplotlib runtime hook creates a temporary directory before the
entry point runs. Directory workers never import matplotlib, and cancellation
can terminate them before atexit cleanup. Normal GUI launches retain the same
secure cache creation and cleanup as PyInstaller's default runtime hook.
"""


def _initialize():
    import sys
    directory_only = ((len(sys.argv) == 4 and sys.argv[1] == '--directory-scan-worker')
        or (len(sys.argv) == 3 and sys.argv[1] == '--verify-directory-scan-wait'))
    if directory_only:
        return
    import atexit
    import os
    import shutil
    from _pyi_rth_utils.tempfile import secure_mkdtemp
    folder = secure_mkdtemp()
    os.environ['MPLCONFIGDIR'] = folder
    atexit.register(shutil.rmtree, folder, ignore_errors=True)


_initialize()
del _initialize
