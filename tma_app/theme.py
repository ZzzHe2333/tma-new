"""Shared pastel Qt theme. Plot fonts, data colours and geometry stay independent."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap, QBrush
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMdiArea

ASSETS = Path(__file__).parent / "assets" / "cute"

# Preserve the established spacing: this theme changes surfaces, not the layout.
CUTE_STYLE = """
QWidget { color: #453c56; font-family: 'Tahoma', 'SimSun'; font-size: 12px; }
QMainWindow, QDialog, QMenuBar, QToolBar, QStatusBar { background: #fff8fc; }
QMenuBar { spacing: 0px; border-bottom: 1px solid #e5d7eb; min-height: 20px; max-height: 20px; }
QMenuBar::item { padding: 0px 8px; height: 18px; background: transparent; border-radius: 5px; }
QMenuBar::item:selected { background: #f4dcea; color: #684563; }
QMenu { background: #fffafd; border: 1px solid #decde7; border-radius: 5px; }
QMenu::item { padding: 3px 26px 3px 22px; border-radius: 4px; }
QMenu::item:selected { background: #eee3f7; color: #594473; }
QMenu::item:disabled { color: #a99daf; }
QMenu::separator { height: 1px; background: #eadfec; margin: 3px 8px; }
QToolBar { border-top: 1px solid #fffefe; border-bottom: 1px solid #e5d7eb; spacing: 0px; padding: 0px 2px; background: #fcf5fb; }
QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; border-radius: 6px; }
QToolButton:hover { border: 1px solid #dec5dd; background: #f8e4ef; }
QToolButton:pressed, QToolButton:checked { border: 1px solid #cbb4dc; background: #e9def5; }
QPushButton { background: #f3e9fa; color: #59486d; border: 1px solid #d9c7e5; min-width: 65px; padding: 4px 8px; border-radius: 6px; }
QPushButton:hover { background: #fbe3ee; border-color: #d8abc6; }
QPushButton:pressed { background: #e9d7f3; border-color: #b898cc; }
QPushButton:default, QPushButton#primary { background: #e0f2e9; color: #365f52; border: 1px solid #b7dace; }
QPushButton:default:hover, QPushButton#primary:hover { background: #cfeadf; }
QPushButton:disabled { background: #f4eff6; border-color: #e6dfe9; color: #a99daf; }
QPushButton:focus, QToolButton:focus { border-color: #a68abf; }
QPushButton#BatchLatest:checked, QPushButton#BatchAll:checked { background: #dcefe5; border-color: #b0d4c3; color: #365f52; }
QPushButton#BatchIssues:checked { background: #f9e1ec; border-color: #dcb5ca; color: #84536f; }
QPushButton#SingleReportButton, QPushButton#BatchProcessingButton { background: #e0f2e9; border-color: #b7dace; color: #365f52; min-width: 94px; max-width: 94px; }
QPushButton#SingleReportButton:hover, QPushButton#BatchProcessingButton:hover { background: #cfeadf; }
QGroupBox { background: #fcf6fc; border: 1px solid #e2d3e9; margin-top: 9px; padding: 8px; border-radius: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; color: #795982; }
QLabel { background: transparent; }
QLabel#muted { color: #8b7996; }
QTreeWidget, QTableView, QPlainTextEdit, QTextEdit { background: #fffefe; alternate-background-color: #fcf7fd; border: 1px solid #decfe6; border-radius: 5px; color: #453c56; selection-background-color: #e8def4; selection-color: #594473; gridline-color: #ebdfed; }
QLineEdit { background: #fffefe; color: #453c56; border: 1px solid #decfe6; border-radius: 4px; padding: 1px; selection-background-color: #e8def4; selection-color: #594473; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #fffefe; color: #453c56; border: 1px solid #decfe6; padding: 2px; border-radius: 4px; min-height: 15px; selection-background-color: #e8def4; selection-color: #594473; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color: #bda0d3; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #aa9daf; background: #f4eff6; border-color: #e6dfe9; }
QComboBox QAbstractItemView { background: #fffafd; color: #453c56; selection-background-color: #e8def4; selection-color: #594473; border: 1px solid #decfe6; }
QComboBox::drop-down { border: none; background: transparent; }
QComboBox::down-arrow { image: url('@ASSETS@/down.svg'); width: 10px; height: 10px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button { border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url('@ASSETS@/up.svg'); width: 8px; height: 8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url('@ASSETS@/down.svg'); width: 8px; height: 8px; }
QCheckBox::indicator { width: 12px; height: 12px; border: 1px solid #cbb8d7; border-radius: 4px; background: #fffefe; }
QCheckBox::indicator:checked { image: url('@ASSETS@/check.svg'); background: #dcefe5; border-color: #accdbc; }
QCheckBox::indicator:indeterminate { image: url('@ASSETS@/minus.svg'); background: #e8def4; }
QCheckBox::indicator:disabled { background: #f1edf4; border-color: #dfd6e5; }
QRadioButton::indicator { width: 12px; height: 12px; border: 1px solid #cbb8d7; border-radius: 7px; background: #fffefe; }
QRadioButton::indicator:checked { image: url('@ASSETS@/dot.svg'); background: #f2e8f8; border-color: #baa0ce; }
QRadioButton::indicator:disabled { background: #f1edf4; border-color: #dfd6e5; }
QHeaderView::section { background: #f3eafa; color: #6f567e; padding: 3px; border: 1px solid #e0d3e7; }
QTableCornerButton::section { background: #f3eafa; border: 1px solid #e0d3e7; }
QTabWidget::pane { border: 1px solid #decfe6; background: #fff8fc; border-radius: 5px; }
QTabBar::tab { background: #f2eaf7; color: #806b8a; border: 1px solid #decfe6; padding: 2px 7px; margin: 0; border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:selected { background: #fff8fc; color: #674b7b; border-bottom-color: #fff8fc; }
QTabBar::tab:hover { background: #f9e6ef; }
QStatusBar { border-top: 1px solid #fffefe; min-height: 18px; color: #89748f; }
QStatusBar::item { border: 1px solid #e7dcea; border-radius: 3px; }
QSplitter::handle { background: #eee2f1; }
QScrollArea { border: 1px solid #e2d3e9; border-radius: 5px; }
QToolTip { background: #fff4f9; color: #674b68; border: 1px solid #dcbfd5; padding: 4px 6px; border-radius: 5px; }
QProgressBar { border: 1px solid #decfe6; border-radius: 5px; background: #fcf6fc; text-align: center; }
QProgressBar::chunk { background: #bddfd0; border-radius: 4px; }
QMdiArea { background: #faf3fc; }
QMdiSubWindow { background: #fff8fc; }
""".replace("@ASSETS@", ASSETS.as_posix())


def cute_palette():
    palette = QPalette(QApplication.palette())
    for role, color in {
        QPalette.ColorRole.Window: "#fff8fc", QPalette.ColorRole.Button: "#f3e9fa",
        QPalette.ColorRole.Base: "#fffefe", QPalette.ColorRole.AlternateBase: "#fcf7fd",
        QPalette.ColorRole.Text: "#453c56", QPalette.ColorRole.ButtonText: "#59486d",
        QPalette.ColorRole.WindowText: "#453c56", QPalette.ColorRole.Highlight: "#e8def4",
        QPalette.ColorRole.HighlightedText: "#594473", QPalette.ColorRole.Light: "#fffefe",
        QPalette.ColorRole.Midlight: "#f5eaf8", QPalette.ColorRole.Mid: "#decfe6",
        QPalette.ColorRole.Dark: "#b8a2c5", QPalette.ColorRole.Shadow: "#9f87ac",
        QPalette.ColorRole.Link: "#9272b0", QPalette.ColorRole.ToolTipBase: "#fff4f9",
        QPalette.ColorRole.ToolTipText: "#674b68",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#aa9daf"))
    return palette


def _svg_icon(source):
    renderer = QSvgRenderer(source.encode("utf-8"))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


@lru_cache(maxsize=1)
def app_icon():
    return _svg_icon((ASSETS / "app.svg").read_text(encoding="utf-8"))


# Distinct action shapes, sharing one stroke and a restrained accent palette.
_AXES = '<path d="M3 3v18h18"/><path stroke="#bc7f9e" d="M5 17c4 0 4-11 8-11s3 10 7 6"/>'
_POINT = '<circle cx="13" cy="6" r="2.5" fill="#f9dce9"/>'
_RANGE = '<path stroke="#6f9f90" d="M7 4v15M18 4v15"/>'
_GLYPHS = {
    "Open1": '<path fill="#fce4b9" d="M2 7V5h7l3 3h9v12H2z"/><path fill="#fff1d5" d="M2 10h21l-4 10H2z"/>',
    "Print1": '<path fill="#eee2f7" d="M3 8h18v10H3z"/><path fill="#fffafd" d="M6 3h12v6H6zM6 14h12v8H6z"/><path d="M9 17h6M9 19h5"/>',
    "Annotate1": '<path fill="#fce4ed" d="M3 3h18v14H10l-5 4v-4H3z"/><path d="M7 7h10M7 10h8M7 13h5"/>',
    "ManualRescale1": '<path d="M3 10V3h7M14 3h7v7M21 14v7h-7M10 21H3v-7"/><path stroke="#bd86a5" d="m7 7 10 10M7 17 17 7"/>',
    "FullScaleAll1": '<rect x="3" y="3" width="18" height="18" rx="4" fill="#e3f1e9"/><path d="M7 12h10M12 7v10m-8-8 3 3-3 3m10-6-3 3 3 3M9 4l3 3 3-3M9 20l3-3 3 3"/>',
    "CommonScale1": '<path d="M3 3v18h18M8 4v13h13M4 15h16"/>',
    "Signals1": '<path fill="#e6f2ed" d="M3 3h18v18H3z"/><path d="M7 4v16M3 9h18M3 15h18"/><path stroke="#bc7f9e" d="m10 6 2 1 3-2 3 2"/>',
    "ParamsSameAs1": '<rect x="3" y="3" width="12" height="14" rx="2"/><rect x="9" y="8" width="12" height="14" rx="2" fill="#f7e8f3"/><path d="M12 13h6M12 17h6"/>',
    "FullRangeLimits1": _AXES + _RANGE,
    "TimeLimits1": '<circle cx="12" cy="12" r="9" fill="#fce8d4"/><path d="M12 6v6l4 3M10 1h4"/>',
    "TemperatureLimits1": '<path fill="#f8dce7" d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0z"/><path d="M12 7v10M17 6h3M17 10h2"/>',
    "Curve1": _AXES,
    "AutoConfigure1": '<path fill="#fce4ef" d="m12 2 3 6 7 1-5 5 1 8-6-4-6 4 1-8-5-5 7-1z"/><path d="m9 12 2 2 4-4"/>',
    "ManualSetup1": '<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2.5" fill="#e4f2e9"/><circle cx="16" cy="12" r="2.5" fill="#fce3ed"/><circle cx="10" cy="18" r="2.5" fill="#eee1f7"/>',
    "GraphOptions1": '<rect x="2" y="3" width="20" height="18" rx="3" fill="#eee3f8"/><path d="M3 8h18M8 9v11M11 17l3-4 3 2 3-4"/>',
    "AlphaAtX1": _AXES + '<path stroke="#6f9f90" d="m7 15 9-10M12 3v17"/>',
    "AlphaX1ToX21": _AXES + _RANGE + '<path d="m6 17 13-9"/>',
    "AlphaFitX1ToX21": _AXES + _RANGE + '<path d="m6 17 13-12"/><circle cx="10" cy="11" r="1"/><circle cx="15" cy="9" r="1"/>',
    "DimensionChange1": _AXES + '<path stroke="#6f9f90" d="M20 5v12m-2-9 2-3 2 3m-4 6 2 3 2-3M6 17h14M13 5h7"/>',
    "Linear1": '<path fill="#f7dfea" d="M3 19c4-2 4-14 9-14s4 12 9 10z"/><path d="m3 19 18-4M3 21h18"/>',
    "SigHorizontal1": '<path fill="#e1f0e9" d="M3 19c4-2 4-14 9-14s4 12 9 10c-9 0-8 4-18 4z"/><path d="M3 19c10 0 9-4 18-4M3 21h18"/>',
    "PeakMax1": _AXES + _POINT + '<path d="M13 1v2M18 6h3"/>',
    "SignalMax1": _AXES + _POINT,
    "SignalChange1": _AXES + _RANGE + '<circle cx="7" cy="16" r="2" fill="#f8dce8"/><circle cx="18" cy="11" r="2" fill="#e1f1e8"/>',
    "GlassTransition1": '<path d="M3 19h5c6 0 3-13 9-13h4"/><path stroke="#6f9f90" d="m7 22 10-20M3 12h18"/><circle cx="12" cy="12" r="2" fill="#fbdde8"/>',
    "OnsetPoint1": '<path d="M3 19h6c6 0 4-14 12-14"/><path stroke="#6f9f90" d="m10 22 9-20M3 19h18"/><circle cx="12" cy="19" r="2" fill="#fbdde8"/>',
    "Slope1": _AXES + '<path stroke="#6f9f90" d="m5 17 15-12M8 17h10V8"/>',
    "CurveValueAtX1": _AXES + '<path stroke="#6f9f90" d="M15 3v17"/><circle cx="15" cy="8" r="2" fill="#fbdde8"/>',
    "AnalysisOptions1": '<rect x="5" y="4" width="15" height="18" rx="3" fill="#eee2f7"/><rect x="9" y="2" width="7" height="4" rx="2" fill="#e3f1e8"/><path d="m8 11 2 2 3-4M14 11h3M8 17h9"/>',
    "Smooth1": '<path d="M2 16 5 6l4 13 4-14 4 13 5-11" stroke="#c9b5d9"/><path d="M2 14c7-16 11 16 20-3" stroke="#b77b9b"/>',
    "Shift1": '<path d="M3 17c4 0 4-9 8-9s4 9 8 9M6 11c4 0 4-9 8-9s4 9 8 9"/><path stroke="#6f9f90" d="M4 4h6m-3-3 3 3-3 3M17 21h6m-3-3 3 3-3 3"/>',
}


@lru_cache(maxsize=64)
def action_icon(name):
    source = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
              '<g fill="none" stroke="#80638f" stroke-width="1.6" stroke-linecap="round" '
              'stroke-linejoin="round">' + _GLYPHS.get(name, _AXES) + '</g></svg>')
    return _svg_icon(source)


class PastelMdiArea(QMdiArea):
    """A quiet empty state, painted without extra controls or layout changes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        tile = QPixmap(32, 32)
        tile.fill(QColor("#faf3fc"))
        painter = QPainter(tile)
        painter.setPen(QColor("#e9dbef"))
        painter.drawPoint(16, 16)
        painter.end()
        self.setBackground(QBrush(tile))

    def paintEvent(self, event):
        super().paintEvent(event)
        if any(child.isVisible() for child in self.subWindowList()):
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.viewport().rect().center()
        icon = app_icon().pixmap(128, 128)
        painter.drawPixmap(center.x() - 64, center.y() - 115, icon)
        painter.setPen(QColor("#765d86"))
        painter.setFont(QFont("Tahoma", 20))
        painter.drawText(QRectF(0, center.y() + 25, self.width(), 40), Qt.AlignmentFlag.AlignCenter, "ZzzHe TMA Analysis")
        painter.setFont(QFont("Microsoft YaHei", 10))
        painter.setPen(QColor("#a08baa"))
        painter.drawText(QRectF(0, center.y() + 70, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "打开文件，开始分析")
        painter.end()
