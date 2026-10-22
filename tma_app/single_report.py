"""Single-sample reports: supplied internal layout, explicit template opt-in."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import OrderedDict
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading

import fitz
import matplotlib
from PIL import Image, ImageOps, ImageFilter

from . import report_internal_core as core
from .report_template_core import PDFTemplateEditor
from .mass_lookup import lookup_record, _batch_keys
from .path_settings import config_path
from .batch_analysis import serialized

LOGGER = logging.getLogger(__name__)
TEMPLATE_KEYS = ("tmaname", "lijing", "qifawd", "zuidawd", "tmamd", "shengchan")
FIELD_KEYS = ("sample_name", "T1", "T2", "M", "H", "TMA", "D50", "SPAN", "tma_time", "particle_time")
_PARTICLE_CACHE = OrderedDict()
_PARTICLE_LOCK = threading.RLock()


def clear_particle_cache():
    with _PARTICLE_LOCK: _PARTICLE_CACHE.clear()


def p9m_data(path):
    """Network datasets are parsed once per file revision, not per record click."""
    stat = path.stat()
    key = (os.path.normcase(str(path)), stat.st_size, stat.st_mtime_ns, stat.st_ino)
    with _PARTICLE_LOCK:
        if key in _PARTICLE_CACHE:
            _PARTICLE_CACHE.move_to_end(key)
            return _PARTICLE_CACHE[key]
        records = core._p9m_parse_records(str(path))
        checksum = digest(path)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ino) != key[1:]:
            raise ValueError("粒径文件在读取期间发生变化，请重新读取")
        # Drop stale revisions of this path and keep at most four datasets.
        for old in list(_PARTICLE_CACHE):
            if old[0] == key[0]: _PARTICLE_CACHE.pop(old)
        _PARTICLE_CACHE[key] = (records, checksum)
        while len(_PARTICLE_CACHE) > 4: _PARTICLE_CACHE.popitem(last=False)
        return records, checksum


class TemplateError(ValueError):
    """Only template-specific errors may offer internal-layout fallback."""


def digest(path):
    from .cloud_storage import resolve_source
    path = resolve_source(path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _number(value, label, *, allow_zero=False):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"请填写有效的 {label}") from None
    if not math.isfinite(number) or (number < 0 if allow_zero else number <= 0):
        raise ValueError(f"{label} 必须为{'非负' if allow_zero else '正'}数")
    return number


def measurement_datetime(value):
    """Accept the instrument's space/ISO timestamps without guessing file dates."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        date = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if date.tzinfo is not None:
            date = date.astimezone(timezone(timedelta(hours=8)))
        return date.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    # The source helper recursively retries matching date text. Do not pass an
    # invalid calendar date back into that recursion.
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%d-%b-%Y %H:%M:%S",
                "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return ""


def read_tma(path, source, algorithm="auto"):
    from .cloud_storage import resolve_source
    path = resolve_source(path)
    if not path.is_file():
        raise ValueError("请选择有效的 TMA 数据文件")
    text, _ = core.load_text_prefer_tajm(str(path), LOGGER)
    xs, ys, _ = core.extract_xy_from_file(core.parse_lines(text), LOGGER)
    if len(xs) < 5:
        raise ValueError("TMA 有效数据点不足")
    detect = core.detect_T2_T1_super_gradient if algorithm == "super" else core.detect_T2_T1_precise
    t1, t2, details = detect(xs, ys, LOGGER)
    cache = core.build_curve_cache(xs, ys)
    height = core.interpolate_curve_height(t2, cache) - core.interpolate_curve_height(t1, cache)
    mass = lookup_record(path.name, source=source)
    mg = mass.value * (1000 if mass.unit == "g" else 1) if mass.value is not None else None
    fields = dict(sample_name=path.stem, T1=f"{t1:.2f}", T2=f"{t2:.2f}",
                  H=core.format_height_um(height), M="" if mg is None else f"{mg:.4f}",
                  tma_time=core._extract_tma_internal_datetime(str(path), LOGGER))
    # The supplied UI calculates density from its displayed/edited H value.
    if mg is not None:
        fields["TMA"] = f"{core.calc_tma_from_m_h(mg, float(fields['H'])):.3f}"
    return dict(file=str(path), sha256=digest(path), xs=xs, ys=ys, fields=fields, details=details,
                algorithm=algorithm, mass_source=mass.source, mass_config=source,
                warning="" if mg is not None else mass.message)


def _pdf_metric(page, label):
    """Read inline labels or adjacent table cells without confusing D50/D75."""
    words = page.get_text("words", sort=True)
    normalized = label.casefold()
    numeric = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
    exact = re.compile(r"^" + re.escape(label) + r"(?:\s*[(:：]|$)", re.I)
    for word in words:
        token = word[4].strip()
        inline = re.match(r"^" + re.escape(label) + r"\s*[:：=]\s*([-+]?\d+(?:\.\d+)?)", token, re.I)
        if inline:
            return float(inline.group(1))
        if not (token.casefold() == normalized or exact.match(token)):
            continue
        x0, y0, x1, y1 = word[:4]
        same_row = [w for w in words if w[0] >= x1-1 and abs((w[1]+w[3]-y0-y1)/2) <= 4]
        same_row.sort(key=lambda w: w[0])
        for candidate in same_row:
            text = candidate[4].strip()
            if re.match(r"^(?:D\d+|SPAN)$", text, re.I):
                break  # Another column heading, not this label's value.
            if numeric.fullmatch(text):
                return float(text)
        below = [w for w in words if y1-1 <= w[1] <= y1+65 and numeric.fullmatch(w[4])
                 and abs((w[0]+w[2]-x0-x1)/2) < max(18, x1-x0)]
        if below:
            below.sort(key=lambda w: (w[1]-y1, abs((w[0]+w[2]-x0-x1)/2)))
            return float(below[0][4])
    # Covers PDFs storing an entire label/value line in a single text run.
    text = page.get_text("text", sort=True)
    match = re.search(r"\b" + re.escape(label) + r"\b\s*[:：=]?\s*(?:[（(][^\n)）]{0,10}[)）]\s*)?([-+]?\d+(?:\.\d+)?)", text, re.I)
    return float(match.group(1)) if match else None


def _image_metrics(image):
    """Use the supplied report's two scaled numeric crop regions."""
    try:
        import pytesseract
        executable = Path(os.environ.get("TMA_TESSERACT", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
        if executable.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(executable)
        regions = {"D50": (568, 565, 842, 635), "SPAN": (842, 640, 1090, 720)}
        results = {}
        for key, region in regions.items():
            box = tuple(round(value * (image.width/1413 if i % 2 == 0 else image.height/2000)) for i, value in enumerate(region))
            crop = ImageOps.grayscale(image.crop(box)).resize((max(1, (box[2]-box[0])*3), max(1, (box[3]-box[1])*3)))
            crop = ImageOps.autocontrast(crop.filter(ImageFilter.SHARPEN))
            text = pytesseract.image_to_string(crop, config="--psm 7 -c tessedit_char_whitelist=0123456789.", timeout=8)
            found = re.findall(r"\d+(?:\.\d+)?", text)
            if len(found) == 1:
                results[key] = float(found[0])
        return results
    except Exception:
        return {}


def read_particle(path, sample_name="", record_index=None, *, require_match=False, expected_revision=None):
    from .cloud_storage import resolve_source
    path = resolve_source(path)
    if not path.is_file():
        raise ValueError("请选择有效的粒径文件")
    result = dict(file=str(path), fields={}, records=[], selected_index=None, method="", warning="")
    suffix = path.suffix.casefold()
    if suffix == ".p9m":
        records, checksum = p9m_data(path)
        keys = _batch_keys(Path(sample_name).stem)
        matches = [i for i, record in enumerate(records) if keys & (_batch_keys(record.sample_no) | _batch_keys(record.sample_name))]
        if expected_revision and checksum != expected_revision:
            result.update(records=records, sha256=checksum, matched_indices=matches, method="P9M 原始记录",
                          warning="粒径数据集已更新，已清除旧记录选择；请重新选择测量记录。")
            return result
        index = record_index
        if index is None:
            if len(matches) == 1:
                index = matches[0]
            elif len(matches) > 1:
                averages = [i for i in matches if records[i].is_average]
                if len(averages) == 1:
                    index = averages[0]
                    result["warning"] = f"匹配 {len(matches)} 条测量记录，已选唯一平均记录，可在粒径记录中切换。"
            elif len(records) == 1 and not require_match:
                index = 0
        result.update(records=records, sha256=checksum, selected_index=index, matched_indices=matches, method="P9M 原始记录")
        if index is None:
            result["warning"] = "此 P9M 有多条记录，请选择要使用的粒径记录"
            return result
        if type(index) is not int or not 0 <= index < len(records):
            raise ValueError("所选粒径记录不存在，请重新选择")
        record = records[index]
        result["fields"] = {"D50": core._p9m_n3(record.d50), "SPAN": core._p9m_n3(record.span),
                            "particle_time": measurement_datetime(record.measurement_time)}
        return result
    result["sha256"] = digest(path)
    values = {}
    if suffix == ".pdf":
        with fitz.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass or not doc.page_count:
                raise ValueError("粒径 PDF 无法读取")
            page = doc[0]
            for key in ("D50", "SPAN"):
                value = _pdf_metric(page, key)
                if value is not None:
                    values[key] = value
            result["method"] = "PDF 文本"
            if len(values) < 2:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                for key, value in _image_metrics(image).items():
                    values.setdefault(key, value)
                result["method"] += " / OCR"
    elif suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
        with Image.open(path) as image:
            values = _image_metrics(image.convert("RGB"))
        result["method"] = "图片 OCR"
    else:
        raise ValueError("粒径文件支持 P9M、PDF、PNG、JPG、TIFF")
    for key in ("D50", "SPAN"):
        value = values.get(key)
        if value is not None and math.isfinite(value) and (value > 0 if key == "D50" else value >= 0):
            result["fields"][key] = f"{value:.3f}"
    if len(result["fields"]) < 2:
        result["warning"] = "D50 或 SPAN 未识别，请核对后手动填写"
    return result


def read_sources(tma_path, particle_path, source, *, algorithm="auto", record_index=None, particle_revision=None, progress=None, parts=("tma", "particle")):
    result = dict(fields={}, tma=None, particle=None, warnings=[], errors=[])
    for key, label, path, fn in (
        ("tma", "TMA", tma_path, lambda: read_tma(tma_path, source, algorithm)),
        ("particle", "粒径", particle_path, lambda: read_particle(particle_path, Path(tma_path).stem, record_index, expected_revision=particle_revision)),
    ):
        if not path or key not in parts:
            continue
        if progress:
            progress(f"正在读取{label}文件…")
        try:
            data = fn()
            result[key] = data
            result["fields"].update(data["fields"])
            if data.get("warning"):
                result["warnings"].append(data["warning"])
        except Exception as exc:
            result["errors"].append(f"{label}：{exc}")
    return result


def validate_template(path):
    """No auto-detection: an empty field is always the internal layout."""
    if not str(path).strip():
        return None
    try:
        from .cloud_storage import resolve_source
        path = resolve_source(path)
        if path.suffix.casefold() != ".pdf" or not path.is_file():
            raise ValueError("模板不是有效的 PDF 文件路径")
        with fitz.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass or doc.page_count < 1:
                raise ValueError("模板无法读取或需要密码")
            missing = [key for key in TEMPLATE_KEYS if not doc[0].search_for(key)]
            if missing:
                raise ValueError("第一页缺少占位符：" + "、".join(missing))
        return str(path.resolve())
    except Exception as exc:
        raise TemplateError(str(exc)) from exc


def collect_values(fields, data, *, require_span=True):
    name = str(fields.get("sample_name", "")).strip()
    if not name:
        raise ValueError("请填写报告编号")
    if not data.get("tma") or not data.get("particle"):
        raise ValueError("请先选择并成功读取 TMA 和粒径文件")
    particle = data["particle"]
    if particle["records"] and particle["selected_index"] is None:
        raise ValueError("请选择要使用的 P9M 粒径记录")
    t1 = _number(fields.get("T1"), "T1")
    t2 = _number(fields.get("T2"), "T2")
    if t1 >= t2:
        raise ValueError("T1 必须小于 T2")
    height = _number(fields.get("H"), "H")
    d50 = _number(fields.get("D50"), "D50")
    span_text = str(fields.get("SPAN", "")).strip()
    span = _number(span_text, "SPAN", allow_zero=True) if require_span or span_text else None
    mass = str(fields.get("M", "")).strip()
    if mass:
        _number(mass, "M")
    density = str(fields.get("TMA", "")).strip()
    density = _number(density, "TMA") if density else core.calc_tma_from_m_h(_number(mass, "M"), height)
    return dict(tmaname=name, lijing=f"{d50:.3f}", span="" if span is None else f"{span:.3f}", qifawd=f"{t1:.2f}", zuidawd=f"{t2:.2f}",
                tmamd=f"{density:.3f}", shengchan=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
                tma_time=str(fields.get("tma_time", "")), p9m_time=str(fields.get("particle_time", "")))


class ReportTemplateEditor(PDFTemplateEditor):
    """The V6 placeholder/image workflow, with bounded images and Unicode text."""
    def replace_label(self, search_text, to_value, page_index=0, fontsize=11):
        page = self.doc[page_index]
        instances = page.search_for(str(search_text))
        for rect in instances:
            page.add_redact_annot(rect, fill=False)
        if instances:
            page.apply_redactions(images=0, graphics=0)
        text = str(to_value)
        for rect in instances:
            # Reserve room in the original value cell; avoid clipping long IDs.
            width = min(160, page.rect.width - rect.x0 - 30)
            unicode_text = any(ord(c) > 255 for c in text)
            fontname = "china-s" if unicode_text else "Times-Roman"
            font = fitz.Font(fontname)
            size = min(float(fontsize), max(6., width / max(font.text_length(text, fontsize=1), 1)))
            page.insert_text((rect.x0, rect.y0 + rect.height*.65), text, fontsize=size, fontname=fontname)
        return len(instances)

    def replace_image_centered(self, page_index, image_path):
        # Retain V6's image replacement while bounding both dimensions.
        while self.doc.page_count <= page_index:
            self.doc.new_page()
        page = self.doc[page_index]
        for image in page.get_images(full=True):
            page.delete_image(image[0])
        with Image.open(image_path) as image:
            scale = min(page.rect.width*.75 / image.width, page.rect.height*.75 / image.height)
            width, height = image.width*scale, image.height*scale
        x, y = (page.rect.width-width)/2, (page.rect.height-height)/2
        page.insert_image(fitz.Rect(x, y, x+width, y+height), filename=str(image_path))


def _protect_output(path, request, data):
    target = os.path.normcase(str(Path(path).resolve()))
    sources = [request.get(key) for key in ("tma_path", "particle_path", "template_path")]
    if data.get("tma"):
        sources.extend([data["tma"].get("mass_config"), data["tma"].get("mass_source", "").split(" [", 1)[0]])
    if any(source and os.path.normcase(str(Path(source).resolve())) == target for source in sources):
        raise ValueError("输出 PDF 不能覆盖 TMA、粒径、模板或称量表源文件")


@serialized
def generate_report(request, data=None, *, force_internal=False, progress=None, cancelled=None):
    """An invalid/failed selected template always raises; the GUI asks first."""
    from .cloud_storage import resolve_source
    request = dict(request)
    for key in ("tma_path", "particle_path"):
        if request.get(key): request[key] = str(resolve_source(request[key]))
    if request.get("template_path"):
        try: request["template_path"] = str(resolve_source(request["template_path"]))
        except Exception as exc:
            if not force_internal: raise TemplateError(str(exc)) from exc
    provided_data = data is not None
    if data is None:
        data = read_sources(request["tma_path"], request["particle_path"], request.get("mass_source", ""),
                            algorithm=request.get("algorithm", "auto"), record_index=request.get("record_index"),
                            particle_revision=request.get("particle_revision"), progress=progress)
    if data.get("errors"):
        raise ValueError("\n".join(data["errors"]))
    template = None if force_internal else validate_template(request.get("template_path", ""))
    fields = dict(data["fields"])
    fields.update({key: value for key, value in request.get("fields", {}).items() if provided_data or str(value).strip()})
    values = collect_values(fields, data, require_span=not bool(template))
    for key in ("tma", "particle"):
        source = data[key]
        if str(Path(request[key + "_path"]).resolve()) != source["file"] or digest(source["file"]) != source["sha256"]:
            if key == "particle": clear_particle_cache()
            raise ValueError("源文件已变化，请重新读取信息后生成报告")
    path = Path(request["output_path"]).resolve()
    _protect_output(path, request, data)
    if path.suffix.casefold() != ".pdf":
        raise ValueError("报告输出须为 .pdf")
    work_root = config_path().parent / "report-work"
    work_root.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="report-", dir=work_root) as directory:
        directory = Path(directory)
        tma_image = directory / "tma.tif"
        if progress:
            progress("正在生成 TMA 曲线图…")
        with matplotlib.rc_context({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "SimSun", "DejaVu Sans"], "axes.unicode_minus": False}):
            core.generate_tma_tif(data["tma"]["xs"], data["tma"]["ys"], float(fields["T1"]), float(fields["T2"]),
                                  float(fields["H"]), fields.get("M", ""), str(tma_image), version="Power By ZzzHe")
        particle = data["particle"]
        particle_image = directory / "particle.png"
        if particle["records"]:
            particle_pdf = directory / "particle.pdf"
            core._p9m_generate_pdf(particle["records"][particle["selected_index"]], str(particle_pdf))
            core.pdf_first_page_to_png(str(particle_pdf), str(particle_image), zoom=2)
        elif Path(particle["file"]).suffix.casefold() == ".pdf":
            core.pdf_first_page_to_png(particle["file"], str(particle_image), zoom=2)
        else:
            with Image.open(particle["file"]) as image:
                image.convert("RGB").save(particle_image)
        descriptor, temporary = tempfile.mkstemp(prefix="report-", suffix=".pdf", dir=path.parent)
        os.close(descriptor)
        Path(temporary).unlink()  # PyMuPDF's save expects a new file.
        try:
            if template:
                if progress:
                    progress("正在填充指定 PDF 模板…")
                editor = None
                try:
                    editor = ReportTemplateEditor(template, LOGGER)
                    template_values = {**values, "shengchan": values["shengchan"][:10].replace("-", "/")}
                    for key in TEMPLATE_KEYS:
                        if not editor.replace_label(key, template_values[key], page_index=0):
                            raise ValueError(f"占位符未填充：{key}")
                    editor.replace_image_centered(1, str(tma_image))
                    editor.replace_image_centered(2, str(particle_image))
                    editor.doc.set_metadata({**editor.doc.metadata, "creator": "Power By ZzzHe"})
                    editor.save(temporary)
                except Exception as exc:
                    raise TemplateError(f"模板填充失败：{exc}") from exc
                finally:
                    if editor is not None:
                        editor.close()
            else:
                if progress:
                    progress("正在生成内部版三页报告…")
                core.build_final_pdf_internal(temporary, values, str(tma_image), str(particle_image))
            with fitz.open(temporary) as doc:
                if doc.page_count < 3:
                    raise ValueError("报告页数异常")
            if cancelled is not None and cancelled.is_set():
                raise ValueError("已取消报告生成")
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return dict(path=str(path), mode="template" if template else "internal", fallback=force_internal,
                values=values, fields=fields, data=data)
