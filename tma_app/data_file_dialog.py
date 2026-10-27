"""Application-local data picking: newest first, with per-run directory memory."""
from pathlib import Path

from PySide6.QtWidgets import QDialog
from .async_data_picker import DataFileDialog


def start_folder(owner):
    remembered=getattr(owner,'_last_data_directory','')
    if remembered:return remembered
    import os
    from .path_settings import cached_settings
    snapshot=cached_settings()
    paths=snapshot[1].get('paths',{}) if snapshot is not None else {}
    folder=paths.get('open_folder',paths.get('默认打开文件夹','')) if isinstance(paths,dict) else ''
    return os.path.expandvars(os.path.expanduser(folder.strip())) if isinstance(folder,str) and folder.strip() else str(Path.home())


def get_data_files(parent,caption,filters,*,owner=None,multiple=True):
    owner=owner if owner is not None else parent
    dialog=DataFileDialog(parent,caption,start_folder(owner),filters,multiple=multiple)
    from .path_settings import cached_settings,refresh_in_background
    from PySide6.QtCore import QTimer
    # The first dialog can paint immediately even when initial config I/O is
    # delayed. Apply configured A only if the user has not navigated elsewhere.
    initial=dialog.directory().absolutePath();generation=dialog._navigation
    waiting=cached_settings() is None and not getattr(owner,'_last_data_directory','')
    if waiting:
        refresh_in_background()
        settings_timer=QTimer(dialog);settings_timer.setInterval(40)
        def apply_default():
            if dialog._navigation!=generation:settings_timer.stop();return
            if cached_settings() is None:return
            settings_timer.stop();folder=start_folder(owner)
            if folder!=initial:dialog.setDirectory(folder)
        settings_timer.timeout.connect(apply_default);settings_timer.start()
    try:
        if dialog.exec()!=QDialog.DialogCode.Accepted:return [],''
        files=dialog.selectedFiles()
        if files:
            # Memory only: never replace configured A with the selected B.
            owner._last_data_directory=str(Path(files[0]).absolute().parent)
        return files,dialog.selectedNameFilter()
    finally:
        dialog.stop();dialog.deleteLater()
