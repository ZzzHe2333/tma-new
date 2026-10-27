"""Atomic preference writes with bounded collisions and prompt access errors."""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


def write_json(path, data, *, sort_keys=False, allow_nan=True, durable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # tempfile.mkstemp retries PermissionError on Windows when os.access says
    # the directory is writable. Restricted EXEs can disagree with os.access;
    # that path can spin through hundreds of thousands of denied creations.
    for attempt in range(4):
        temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        except FileExistsError:
            if attempt == 3: raise
            continue
        break
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=sort_keys, allow_nan=allow_nan)
            handle.write('\n')
            if durable:
                handle.flush();os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try: temporary.unlink(missing_ok=True)
        except OSError: pass
