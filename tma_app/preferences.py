"""Page-scoped user preferences; never a session or source-file loader.

Manufacturer evidence: local WinUA Content/winhlp/Button_Save.htm:14 saves the
current window/page to the selected initialization file. The explicit rule in
Win_Main_Options_initialization_page.htm:44 says Save writes only the selected
page and Default recalls only that page's FACTORY settings. Overlay Axes page
line 21 excludes names from saved defaults. See artifacts/help-evidence/overlay.md
for the full page matrix and unresolved metadata cases.

This backend stores user defaults. UI Default must use the application's shipped
factory baseline, NOT load_defaults(). Data-bound filenames, UIDs, source paths,
sample legend strings and data arrays are intentionally outside this preference
format. That conservative boundary is a modern policy, not a claim that every
such field is excluded from the original binary initialization file.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import numbers
import os
from pathlib import Path
import re
import tempfile
import threading

from .workspace import default_plot_options, validate_plot_options

FORMAT = "tma-studio-preferences"
VERSION = 1
PAGE_FIELDS = {
    "graph": {"graph": frozenset(("graph_axis_visible", "graph_grid_types", "graph_symbol_spacing", "graph_show_symbols", "graph_symbol_differentiate")),
              "signals": frozenset(("signal_defaults",))},
    "overlay": {
        "curves": frozenset(),
        "axes": frozenset(("axis_flags", "axis_x_offsets")),
        "title": frozenset(("title", "window_name", "export_title", "export_align")),
        "legend": frozenset(("legend", "legend_location", "legend_border", "legend_color", "legend_text", "legend_line", "legend_file", "legend_symbol", "legend_anchor")),
        "grid": frozenset(("grid_x", "grid_y", "grid_minor", "graph_grid_types")),
        "auto": frozenset(("auto_x", "auto_y", "overlay_auto")),
        "configure": frozenset(("overlay_configure",)),
    },
}
# Opaque future option values: reserve the names without inventing nested schema.
RESERVED_FIELDS = frozenset(("axis_x_offsets",))
STYLES = frozenset(("-", "--", "-.", ":", "None", "long_dash", "broken_dash", "broken_double_dash"))
MARKERS = frozenset(("", "o", "s", "^", "v", "+", "x", ".", "D"))
_LOCK = threading.RLock()


def preferences_path():
    """Only this application-selected path is accessed; JSON values are inert."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / "AppData" / "Local"
    return root / "TMA-Studio" / "preferences.json"


def _scope_page(scope, page=None):
    if scope not in PAGE_FIELDS:
        raise ValueError("无效的默认设置范围")
    if page is not None and page not in PAGE_FIELDS[scope]:
        raise ValueError("无效的默认设置页面")


def _empty():
    return {"format": FORMAT, "version": VERSION, "scopes": {}}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("默认设置包含重复 JSON 字段")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("默认设置包含非有限数值")


def _json_copy(value, depth=0):
    """Copy safe JSON values, with finite numbers; no objects or path execution."""
    if depth > 20:
        raise ValueError("默认设置嵌套过深")
    if value is None or type(value) is bool or isinstance(value, str):
        return value
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError("默认设置包含非有限数值")
        return int(value) if isinstance(value, numbers.Integral) else float(value)
    if isinstance(value, (list, tuple)):
        return [_json_copy(item, depth+1) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_copy(item, depth+1) for key, item in value.items()}
    raise ValueError("默认设置只能包含 JSON 数据")


def _options(scope, page, options, *, strict=False):
    if not isinstance(options, dict):
        raise ValueError("默认绘图设置必须是字典")
    allowed = PAGE_FIELDS[scope][page]
    if strict and set(options) - allowed:
        raise ValueError("默认设置含有不属于该页面的字段")
    selected = {key: _json_copy(value) for key, value in options.items() if key in allowed}
    # Reuse the canonical strict validators for fields already defined by workspace.
    known = set(default_plot_options())
    validated = validate_plot_options({key: value for key, value in selected.items() if key in known})
    return {key: deepcopy(validated[key]) if key in known else value for key, value in selected.items()}


def _appearance(value, scope, *, strict=False):
    fields = ("style", "color", "marker", "offset") if scope == "overlay" else ("style", "color", "marker")
    if isinstance(value, dict):
        if strict and set(value) != set(fields):
            raise ValueError("曲线默认外观字段无效")
        try:
            result = {key: value[key] for key in fields}
        except KeyError as exc:
            raise ValueError("曲线默认外观缺少字段") from exc
    else:
        try:
            result = {key: getattr(value, key) for key in fields}
            if scope == "overlay" and hasattr(value, "overlay_offset"): result["offset"] = value.overlay_offset
        except AttributeError as exc:
            raise ValueError("曲线默认外观缺少字段") from exc
    if not isinstance(result["style"], str) or result["style"] not in STYLES:
        raise ValueError("默认曲线线型无效")
    if not isinstance(result["color"], str) or re.fullmatch(r"#[0-9a-fA-F]{6}", result["color"]) is None:
        raise ValueError("默认曲线颜色无效")
    if not isinstance(result["marker"], str) or result["marker"] not in MARKERS:
        raise ValueError("默认曲线符号无效")
    if scope == "overlay":
        offset = result["offset"]
        if isinstance(offset, bool) or not isinstance(offset, numbers.Real) or not math.isfinite(offset):
            raise ValueError("默认曲线偏移必须是有限数值")
        result["offset"] = float(offset)
    return result


def _curves(curves, scope, *, grouped=False, strict=False):
    """Return four ordered axis lists. Caller selects the relevant live curves.

    Accept either flat Curve-like objects/dicts with axis, or four grouped lists.
    Only appearance is retained; no source reference is serialized.
    """
    if not isinstance(curves, (list, tuple)):
        try:
            curves = list(curves)
        except TypeError as exc:
            raise ValueError("默认曲线外观必须是序列") from exc
    result = [[], [], [], []]
    if grouped or (len(curves) == 4 and all(isinstance(axis, (list, tuple)) for axis in curves)):
        if len(curves) != 4:
            raise ValueError("默认曲线外观必须包含四个坐标轴")
        for axis, slots in enumerate(curves):
            if not isinstance(slots, (list, tuple)) or len(slots) > 10:
                raise ValueError("每轴默认曲线最多十个外观槽")
            result[axis] = [_appearance(slot, scope, strict=strict) for slot in slots]
    else:
        for curve in curves:
            axis = curve.get("axis") if isinstance(curve, dict) else getattr(curve, "axis", None)
            if isinstance(axis, bool) or not isinstance(axis, numbers.Integral) or not 0 <= axis < 4:
                raise ValueError("默认曲线坐标轴无效")
            result[int(axis)].append(_appearance(curve, scope))
            if len(result[int(axis)]) > 10:
                raise ValueError("每轴默认曲线最多十个外观槽")
    return result


def _read(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return _empty()
    try:
        document = json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("默认设置文件无效，未覆盖已有文件") from exc
    if (not isinstance(document, dict) or set(document) != {"format", "version", "scopes"}
            or document.get("format") != FORMAT or type(document.get("version")) is not int
            or document["version"] != VERSION or not isinstance(document.get("scopes"), dict)):
        raise ValueError("默认设置文件格式或版本无效")
    for scope, pages in document["scopes"].items():
        _scope_page(scope)
        if not isinstance(pages, dict):
            raise ValueError("默认设置页面映射无效")
        for page, state in pages.items():
            _scope_page(scope, page)
            allowed = {"options", "curves"} if page in ("graph", "curves") else {"options"}
            if not isinstance(state, dict) or set(state) != allowed:
                raise ValueError("默认设置页面结构无效")
            _options(scope, page, state["options"], strict=True)
            if "curves" in state:
                _curves(state["curves"], scope, grouped=True, strict=True)
    return document


def load_defaults(scope, *, path=None):
    """Load ONLY saved user fields, not factory defaults or document names.

    Missing file/scope returns empty options and four empty appearance lists.
    Invalid existing preferences raise ValueError, never silently disappear.
    """
    _scope_page(scope)
    target = Path(path) if path is not None else preferences_path()
    with _LOCK:
        document = _read(target)
    options, curves = {}, [[], [], [], []]
    pages = document["scopes"].get(scope, {})
    for page in PAGE_FIELDS[scope]:
        state = pages.get(page)
        if state is not None:
            options.update(_options(scope, page, state["options"], strict=True))
            if "curves" in state:
                curves = _curves(state["curves"], scope, grouped=True, strict=True)
    return {"options": options, "curves": curves}


def save_defaults(scope, page, options, curves=(), *, path=None):
    """Atomically replace one preference page, preserving all others/scopes.

    Unknown input options are excluded by the page whitelist. Graph appearance
    omits offsets; overlay appearance stores style/color/marker/offset only.
    Invalid old files raise ValueError. Any write/replace failure leaves old bytes.
    """
    _scope_page(scope, page)
    state = {"options": _options(scope, page, options)}
    if page in ("graph", "curves"):
        state["curves"] = _curves(curves, scope)
    target = Path(path) if path is not None else preferences_path()
    with _LOCK:
        document = _read(target)
        document["scopes"].setdefault(scope, {})[page] = state
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            handle, name = tempfile.mkstemp(prefix=".preferences-", suffix=".tmp", dir=target.parent)
            temporary = Path(name)
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
                json.dump(document, output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
                output.write("\n"); output.flush(); os.fsync(output.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
    return target
