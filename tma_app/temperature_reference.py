"""Reference lines and intersections in the displayed temperature coordinates."""
import re

import numpy as np


KIND = "temperature_reference"


def validate_lines(lines):
    from .workspace import _number, _validate_label_style

    if not isinstance(lines, list):
        raise ValueError("温度参考线设置无效")
    validated = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise ValueError("温度参考线设置无效")
        temperature = _number(entry.get("temperature"), "参考线温度")
        color = entry.get("color")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("温度参考线颜色无效")
        annotation = entry.get("annotation", {})
        if not isinstance(annotation, dict):
            raise ValueError("温度参考线标签设置无效")
        offsets = annotation.get("label_offsets", {})
        if not isinstance(offsets, dict):
            raise ValueError("温度参考线标签位置无效")
        clean_offsets = {}
        for key, pair in offsets.items():
            if not isinstance(key, str) or not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("温度参考线标签位置无效")
            clean_offsets[key] = [_number(value, "温度参考线标签位置") for value in pair]
        clean_annotation = {"label_offsets": clean_offsets}
        styles = annotation.get("label_styles", {})
        if not isinstance(styles, dict):
            raise ValueError("温度参考线标签样式无效")
        if styles:
            clean_styles = {}
            for key, style in styles.items():
                if not isinstance(key, str):
                    raise ValueError("温度参考线标签样式无效")
                _validate_label_style(style)
                clean_styles[key] = dict(style)
            clean_annotation["label_styles"] = clean_styles
        validated.append(dict(kind=KIND, temperature=temperature, color=color, annotation=clean_annotation))
    return validated


def intersections(x, y, rows, temperature):
    """Interpolate each crossing along connected acquisition segments."""
    exact = x == temperature
    connected = np.diff(rows) == 1
    # A run of consecutive samples on the reference has infinitely many
    # intersections. Label its first sample once and keep isolated exact hits.
    first_exact = exact.copy()
    first_exact[1:] &= ~(exact[:-1] & connected)
    crosses = connected & (
        ((x[:-1] < temperature) & (temperature < x[1:])) |
        ((x[1:] < temperature) & (temperature < x[:-1]))
    )
    for index in np.flatnonzero(first_exact | np.r_[crosses, False]):
        if first_exact[index]:
            yield int(rows[index]), float(y[index])
        else:
            fraction = (temperature - x[index]) / (x[index + 1] - x[index])
            height = (1 - fraction) * y[index] + fraction * y[index + 1]
            yield int(rows[index]), float(height)


def render(owner, entries, fonts, fontsize):
    from matplotlib.lines import Line2D
    from .dimension_units import quantity
    from .measurement import apply_text_style

    base = owner.axes[0]
    if owner._plot_artists:
        temperature_curve = owner._plot_artists[0][0]
    else:
        temperature_curve = next(iter(owner._document_curves(owner.active_document())), None)
    temperature_unit = temperature_curve.x_unit("temperature") if temperature_curve is not None else ""
    temperature_transform = base.get_xaxis_transform()
    curves = [(curve, owner.axes[curve.axis], quantity(curve)["unit"],
               x + owner.display_x_offset(curve), y, curve.active_rows)
              for curve, x, y in owner._plot_artists]
    for entry in entries:
        x_ref, color = entry["temperature"], entry["color"]
        base.add_artist(Line2D([x_ref, x_ref], [0, 1], transform=temperature_transform,
                               color=color, lw=.85, zorder=3))
        base.annotate(f"{x_ref:.12g} {temperature_unit}".rstrip(), (x_ref, 1),
                      xycoords=temperature_transform, xytext=(0, 4), textcoords="offset points",
                      ha="center", va="bottom", color=color, fontfamily=fonts, fontsize=fontsize,
                      annotation_clip=True, zorder=5, gid="tma-temperature-reference-caption")
        offsets = entry["annotation"].get("label_offsets", {})
        for curve, axis, unit, x, y, rows in curves:
            for row, height in intersections(x, y, rows, x_ref):
                key = f"{curve.uid}:{row}"
                caption = f"{height:.12g} {unit}".rstrip()
                axis.add_artist(Line2D([x_ref], [height], color=color, marker="o", ms=3.5,
                                       linestyle="None", zorder=4))
                label = axis.annotate(caption, (x_ref, height), xytext=offsets.get(key, (8, 10)),
                                      textcoords="offset points", color=color, fontfamily=fonts,
                                      fontsize=fontsize, annotation_clip=True, zorder=5,
                                      arrowprops=dict(arrowstyle="-", color=color, lw=.65))
                label._tma_offset_key = key
                label._tma_visibility_caption = f"{curve.dataset.display_name} · {caption}"
                apply_text_style(entry, label)
                owner._result_annotations.append((entry, label))


def edit_dialog(owner, temperature, color, unit, *, editing=False):
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from PySide6.QtWidgets import QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton

    dialog = QDialog(owner)
    dialog.setWindowTitle("编辑温度参考线" if editing else "温度参考线")
    layout = QFormLayout(dialog)
    field = QLineEdit(f"{temperature:.12g}", dialog)
    layout.addRow(f"温度（{unit}）" if unit else "温度", field)
    color_button = QPushButton(dialog)
    layout.addRow("颜色", color_button)
    error = QLabel(dialog)
    layout.addRow(error)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    layout.addRow(buttons)
    settings = None

    def set_color(value):
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(value))
        color_button.setIcon(QIcon(swatch))
        color_button.setText(value)

    def choose_color():
        picked = QColorDialog.getColor(QColor(color_button.text()), dialog, "选择温度参考线颜色")
        if picked.isValid():
            set_color(picked.name())

    def accept():
        nonlocal settings
        try:
            settings = validate_lines([dict(temperature=float(field.text()), color=color_button.text())])[0]
        except ValueError:
            error.setText("请输入有效的温度数值。")
            return
        dialog.accept()

    set_color(color)
    color_button.clicked.connect(choose_color)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    field.setFocus()
    field.selectAll()
    dialog.exec()
    dialog.deleteLater()
    return settings
