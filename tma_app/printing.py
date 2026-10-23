"""One-page A4 plot printing; preview and the physical job share a renderer."""
from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import QMarginsF, QRectF, QTimer, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox,
    QDoubleSpinBox, QLabel, QDialogButtonBox)

from .path_settings import _settings_data, _save_data

PAPERS = (('A4', QPageSize.PageSizeId.A4), ('A3', QPageSize.PageSizeId.A3),
          ('A5', QPageSize.PageSizeId.A5), ('Letter', QPageSize.PageSizeId.Letter))
DEFAULTS = {'paper': 'A4', 'orientation': 'auto', 'margins_mm': [10., 10., 10., 10.]}


def validate(value):
    if not isinstance(value, dict): raise ValueError('打印设置格式无效')
    result = {**deepcopy(DEFAULTS), **value}
    if result['paper'] not in dict(PAPERS): raise ValueError('请选择有效纸张')
    if result['orientation'] not in ('auto', 'landscape', 'portrait'): raise ValueError('请选择打印方向')
    margins = result['margins_mm']
    if (not isinstance(margins, (list, tuple)) or len(margins) != 4 or
        any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 50 for v in margins)):
        raise ValueError('页边距须为 0–50 毫米')
    result['margins_mm'] = list(map(float, margins))
    return {key: result[key] for key in DEFAULTS}


def settings():
    return validate(_settings_data().get('printing', {}))


def save_settings(value):
    value = validate(value)
    data = _settings_data(); data['printing'] = value
    return _save_data(data)


def make_printer(value, size, *, title='TMA', output_pdf=None):
    value = validate(value)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if output_pdf is not None:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output_pdf))
    printer.setResolution(300)
    printer.setDocName(title); printer.setCreator('Power By ZzzHe')
    landscape = (size.width() >= size.height()) if value['orientation'] == 'auto' else value['orientation'] == 'landscape'
    if not printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait):
        raise ValueError('打印机不支持所选打印方向。')
    if not printer.setPageSize(QPageSize(dict(PAPERS)[value['paper']])):
        raise ValueError('打印机不支持所选纸张，请调整打印设置。')
    layout = printer.pageLayout(); layout.setUnits(QPageLayout.Unit.Millimeter)
    minimum = layout.minimumMargins()
    margins = QMarginsF(*[max(requested, actual) for requested, actual in zip(value['margins_mm'],
        (minimum.left(), minimum.top(), minimum.right(), minimum.bottom()))])
    if not printer.setPageMargins(margins, QPageLayout.Unit.Millimeter):
        raise ValueError('打印机不支持所选页边距，请调整打印设置。')
    printer.setFullPage(False)
    return printer


def fitted_rect(page, size):
    """Fit the complete image inside the printable rectangle, centered."""
    if size.width() <= 0 or size.height() <= 0 or page.width() <= 0 or page.height() <= 0:
        raise ValueError('图像或打印区域为空')
    scale = min(page.width()/size.width(), page.height()/size.height())
    width, height = size.width()*scale, size.height()*scale
    return QRectF(page.x()+(page.width()-width)/2, page.y()+(page.height()-height)/2, width, height)


def paint_page(printer, image):
    if image.isNull(): raise ValueError('当前图像为空，无法打印。')
    painter = QPainter()
    if not painter.begin(printer): raise OSError('无法开始打印，请检查打印机或输出文件位置。')
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = fitted_rect(QRectF(painter.viewport()), image.size())
        painter.drawImage(target, image, QRectF(image.rect()))
        return target
    finally:
        painter.end()


class PrintSettingsDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.owner)
        self.controller = controller
        self.setObjectName('PrintSettingsDialog'); self.setWindowTitle('打印设置')
        self.resize(440, 330)
        layout = QVBoxLayout(self)
        hint = QLabel('默认 A4，自动根据图像选择横向或纵向。整张图等比例居中，保留标题、坐标、标注和外围白边。打印机的最小页边距大于设置时，以设备限制为准。')
        hint.setWordWrap(True); layout.addWidget(hint)
        form = QFormLayout()
        self.paper = QComboBox()
        for key, _ in PAPERS: self.paper.addItem(key, key)
        self.paper.setCurrentIndex(self.paper.findData(controller.options['paper']))
        self.orientation = QComboBox()
        for key, text in (('auto', '自动 · 随图像方向'), ('landscape', '横向'), ('portrait', '纵向')):
            self.orientation.addItem(text, key)
        self.orientation.setCurrentIndex(self.orientation.findData(controller.options['orientation']))
        form.addRow('纸张', self.paper); form.addRow('打印方向', self.orientation)
        self.margins = []
        for text, value in zip(('左边距', '上边距', '右边距', '下边距'), controller.options['margins_mm']):
            field = QDoubleSpinBox(); field.setRange(0, 50); field.setDecimals(1)
            field.setSuffix(' mm'); field.setValue(value); field.setKeyboardTracking(False)
            self.margins.append(field); form.addRow(text, field)
        layout.addLayout(form)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def accept(self):
        try:
            value = validate({'paper': self.paper.currentData(), 'orientation': self.orientation.currentData(),
                              'margins_mm': [field.value() for field in self.margins]})
            saved = save_settings(value)
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc)); return
        self.controller.options = value
        self.controller.owner.statusBar().showMessage(f'打印设置已保存：{saved}')
        super().accept()


class PrintController:
    def __init__(self, owner):
        self.owner = owner
        self.options = settings()

    def _existing(self, key):
        dialog = self.owner.dialogs.get(key)
        if dialog is not None:
            dialog.raise_(); dialog.activateWindow()
        return dialog

    def _show(self, key, dialog):
        self.owner.dialogs[key] = dialog
        def finished():
            if self.owner.dialogs.get(key) is dialog: self.owner.dialogs.pop(key, None)
            # A print preview holds a full-resolution snapshot and QPictures.
            # Release them on close instead of accumulating hidden previews.
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        return dialog

    def show_settings(self):
        existing = self._existing('print_settings')
        if existing is not None: return existing
        dialog = PrintSettingsDialog(self)
        return self._show('print_settings', dialog)

    def snapshot(self):
        if not self.owner.visible_curves():
            self.owner.statusBar().showMessage('请先打开需要打印的图像。'); return None
        # Capture once per job: previews, repeated repaints and Print all use the
        # same active document and export heading, without changing the plot.
        image = self.owner.output_pixmap(dpi=300).toImage()
        document = self.owner.active_document()
        title = document.windowTitle() if document else 'TMA'
        return image, make_printer(self.options, image.size(), title=title)

    def preview(self):
        existing = self._existing('print_preview')
        if existing is not None: return existing
        job = self.snapshot()
        if job is None: return
        image, printer = job
        dialog = QPrintPreviewDialog(printer, self.owner)
        dialog.setObjectName('PlotPrintPreview'); dialog.setWindowTitle('打印预览 · '+printer.docName())
        dialog.resize(1000, 720)
        dialog._plot_image = image; dialog._plot_printer = printer; dialog._print_error = None
        def paint(target):
            try: paint_page(target, image)
            except (ValueError, OSError) as exc:
                if dialog._print_error is None:
                    dialog._print_error = str(exc)
                    QTimer.singleShot(0, lambda: self.owner.warn(dialog._print_error))
        dialog.paintRequested.connect(paint)
        return self._show('print_preview', dialog)

    def print_plot(self):
        job = self.snapshot()
        if job is None: return
        image, printer = job
        dialog = QPrintDialog(printer, self.owner)
        dialog.setWindowTitle('打印图像'); dialog.setMinMax(1, 1)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        paint_page(printer, image)


def controller(owner):
    value = getattr(owner, '_print_controller', None)
    if value is None:
        value = PrintController(owner); owner._print_controller = value
    return value
