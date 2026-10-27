"""Plain settings I/O jobs. No widget or QObject crosses a worker boundary."""
def load(primary,events):
    try:
        from .path_settings import _read_settings, validate_dialog_settings
        from .ui_size import saved_size
        location,data=_read_settings(primary=primary)
        validate_dialog_settings(data)
        events.put(('loaded',location,data,saved_size()))
    except Exception as exc:events.put(('load_error',str(exc)))


def save(paths,popup,hours,events):
    try:
        from .path_settings import save_settings
        location=save_settings(paths,batch_popup=popup,cache_hours=hours)
        events.put(('saved',location,paths))
    except Exception as exc:events.put(('save_error',str(exc)))
