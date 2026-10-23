"""Model-backed batch view; rows are plain data, never QTableWidgetItem owners."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import QTableView
from . import batch_analysis as backend


class BatchTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent); self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    @staticmethod
    def tooltip(row):
        parts = [row['batch_label'], row['file'], row['state']]
        parts += [str(row[key]) for key in ('error','warning','mass_source','export_error','png') if row.get(key)]
        return '\n'.join(parts)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows): return None
        row = self.rows[index.row()]; key = backend.KEYS[index.column()]
        if role == Qt.ItemDataRole.DisplayRole: return backend.display_value(row, key)
        if role == Qt.ItemDataRole.ToolTipRole: return self.tooltip(row)
        if role == Qt.ItemDataRole.TextAlignmentRole: return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.BackgroundRole and (row.get('error') or key == 'M' and row.get('warning')):
            return QColor('#fff0e6')
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            return backend.HEADERS[section] if role == Qt.ItemDataRole.DisplayRole and 0 <= section < 4 else None
        if not 0 <= section < len(self.rows): return None
        row = self.rows[section]
        if role == Qt.ItemDataRole.DisplayRole: return f"{section+1}  {row['name']}"
        if role == Qt.ItemDataRole.ToolTipRole: return self.tooltip(row)
        if role == Qt.ItemDataRole.ForegroundRole and row.get('error'): return QColor('#ad526c')
        return None

    def set_rows(self, rows):
        if [r['id'] for r in rows] == [r['id'] for r in self.rows]:
            self.rows = list(rows)
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows)-1, 3))
                self.headerDataChanged.emit(Qt.Orientation.Vertical, 0, len(rows)-1)
            return
        self.beginResetModel(); self.rows = list(rows); self.endResetModel()

    def refresh_row(self, index):
        if 0 <= index < len(self.rows):
            self.dataChanged.emit(self.index(index, 0), self.index(index, 3))
            self.headerDataChanged.emit(Qt.Orientation.Vertical, index, index)


class ResultsTable(QTableView):
    copy_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_model = BatchTableModel(self)
        self.setModel(self.result_model)

    def rowCount(self): return self.result_model.rowCount()
    def columnCount(self): return self.result_model.columnCount()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit(); event.accept()
        else: super().keyPressEvent(event)
