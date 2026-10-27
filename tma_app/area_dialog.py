"""Independent interval areas and an inspectable table of recorded peak areas."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLabel,QComboBox,QPushButton,QDoubleSpinBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,
    QFileDialog,QAbstractItemView,QCheckBox)

from .area_calculation import BASELINES,FORMULAS,calculate

HEADERS=('文件','方法','积分域','起点X','终点X','净面积','正面积','负面积','绝对面积','单位')
METHODS={'peak_linear':'线性峰积分','peak_sigmoid':'水平S形峰积分','interval_area':'独立区间面积','integral':'旧通用积分'}


class AreaDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.document=owner.active_document()
        self.setWindowTitle('面积计算与公式');self.resize(1060,720)
        self.curves=[c for c in owner.visible_curves() if c.derived is None]
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout=QVBoxLayout(self);form=QFormLayout()
        self.curve=QComboBox()
        for c in self.curves:self.curve.addItem(f'{c.dataset.display_name} · {c.result_label} · Y{c.axis+1}')
        selected=owner.selected();self.curve.setCurrentIndex(self.curves.index(selected) if selected in self.curves else 0)
        form.addRow('曲线',self.curve)
        choices=QHBoxLayout();self.coordinate=QComboBox();self.baseline=QComboBox()
        self.coordinate.addItem('实际记录时间','recorded_time');self.coordinate.addItem('当前绘图X','display_x')
        for key,label in BASELINES.items():self.baseline.addItem(label,key)
        choices.addWidget(QLabel('积分坐标'));choices.addWidget(self.coordinate);choices.addWidget(QLabel('基线'));choices.addWidget(self.baseline)
        form.addRow(choices)
        row=QHBoxLayout();self.bounds=[]
        for text in ('点1 X','点2 X'):
            row.addWidget(QLabel(text));box=QDoubleSpinBox();box.setRange(-1e12,1e12);box.setDecimals(9);box.setKeyboardTracking(False)
            row.addWidget(box);self.bounds.append(box)
        full=QPushButton('全范围');full.clicked.connect(self.full_range);row.addWidget(full)
        self.compute_button=QPushButton('计算并标注');self.compute_button.clicked.connect(self.compute);row.addWidget(self.compute_button)
        form.addRow(row);layout.addLayout(form)
        self.feedback=QLabel();self.feedback.setWordWrap(True);layout.addWidget(self.feedback)
        row=QHBoxLayout();self.all_results=QCheckBox('显示其他图的面积结果');self.all_results.toggled.connect(self.refresh)
        row.addWidget(self.all_results);row.addStretch();refresh=QPushButton('刷新结果');refresh.clicked.connect(self.refresh);row.addWidget(refresh);layout.addLayout(row)
        self.table=QTableWidget(0,len(HEADERS));self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);layout.addWidget(self.table,1)
        self.formulas=QPlainTextEdit(FORMULAS);self.formulas.setReadOnly(True);self.formulas.setMaximumHeight(180);layout.addWidget(self.formulas)
        row=QHBoxLayout()
        for text,callback in (('复制表格',self.copy),('导出 XLSX',self.export),('关闭',self.accept)):
            button=QPushButton(text);button.clicked.connect(callback);row.addWidget(button)
        layout.addLayout(row)
        self.curve.currentIndexChanged.connect(self.full_range)
        for box in self.bounds:box.valueChanged.connect(self.bounds_changed)
        self.full_range();self.refresh()

    def bounds_changed(self,*_):self.exact_positions=None

    def full_range(self,*_):
        if not self.curves:self.feedback.setText('请先打开需要计算面积的曲线。');self.compute_button.setEnabled(False);return
        c=self.curves[self.curve.currentIndex()];x,_=c.xy(self.owner.domain)
        for box,value in zip(self.bounds,(x[0],x[-1])):box.setValue(float(value))
        self.exact_positions=[0.,float(len(x)-1)]

    def compute(self):
        try:
            if self.owner.active_document() is not self.document:raise ValueError('请返回打开此窗口时的曲线图')
            if not self.curves:raise ValueError('请先打开曲线')
            curve=self.curves[self.curve.currentIndex()];x,_=curve.xy(self.owner.domain)
            if self.exact_positions is None:
                from .measurement import position_at_x
                positions=[position_at_x(x,box.value(),anchor,curve.active_rows) for box,anchor in zip(self.bounds,(0,len(x)-1))]
            else:positions=self.exact_positions
            values=calculate(curve,self.owner.domain,positions,coordinate=self.coordinate.currentData(),baseline=self.baseline.currentData())
            result=dict(file=curve.dataset.path.name,sha256=curve.dataset.sha256,curve_id=curve.uid,kind='interval_area',
                domain=self.owner.domain,lo=min(values['start_x'],values['stop_x']),hi=max(values['start_x'],values['stop_x']),
                signal=curve.result_label,operations=list(curve.operations),transform=deepcopy(curve.result_transform(self.owner.domain)),
                values=values,annotation={})
            self.owner.results.append(result);self.owner.touch();self.owner.refresh_results();self.owner.redraw()
            from .achievement_ui import record
            record(self.owner, 'analysis')
            self.refresh();self.feedback.setText(f"已记录：净面积 {values['net_area']:.8g}，绝对面积 {values['absolute_area']:.8g} {values['area_unit']}")
        except (ValueError,OSError) as exc:self.feedback.setText(str(exc))

    def rows(self):
        visible={c.uid for c in self.owner.visible_curves()}
        for r in self.owner.results:
            if r['kind'] not in METHODS or 'integral' not in r['values']:continue
            if not self.all_results.isChecked() and r.get('curve_id') not in visible:continue
            v=r['values'];coordinate=v.get('integration_domain','display_x')
            method=METHODS[r['kind']]+(' · '+BASELINES.get(v.get('baseline_kind'),'') if r['kind']=='interval_area' else '')
            yield [r['file'],method,'实际时间' if coordinate=='recorded_time' else r['domain'],
                v.get('start_x',v.get('x_start','')),v.get('stop_x',v.get('x_end','')),
                v.get('net_area',v['integral']),v.get('positive_area',''),v.get('negative_area',''),v.get('absolute_area',''),v.get('area_unit','')]

    def refresh(self,*_):
        rows=list(self.rows());self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):self.table.setItem(i,j,QTableWidgetItem(format(value,'.10g') if isinstance(value,(int,float)) else str(value)))
        self.table.resizeColumnsToContents()

    def copy(self):
        rows=list(self.rows())
        if not rows:self.feedback.setText('暂无面积结果，请先计算。');return
        QApplication.clipboard().setText('\n'.join('\t'.join(map(str,row)) for row in [HEADERS,*rows]))
        from .achievement_ui import record
        record(self.owner, 'tables')
        self.feedback.setText('已复制面积表格，可粘贴到 Excel。旧结果未记录的分项面积留空，不重新计算或覆盖旧值。')

    def export(self):
        rows=list(self.rows())
        if not rows:self.feedback.setText('暂无面积结果，请先计算。');return
        from .path_settings import import_folder
        path,_=QFileDialog.getSaveFileName(self,'导出面积结果',str(Path(import_folder())/'面积结果.xlsx'),'Excel (*.xlsx)')
        if not path:return
        try:
            self.owner.protect_output(path)
            from openpyxl import Workbook
            book=Workbook();sheet=book.active;sheet.title='面积结果';sheet.append(HEADERS)
            for row in rows:sheet.append(row)
            sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
            formula=book.create_sheet('公式与方法')
            for line in FORMULAS.splitlines():formula.append([line])
            try:book.save(path)
            finally:book.close()
            self.feedback.setText(f'面积结果已导出：{path}')
            from .achievement_ui import record
            record(self.owner, 'tables')
        except (ValueError,OSError) as exc:self.feedback.setText(str(exc))
