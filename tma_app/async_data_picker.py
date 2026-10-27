"""Background file enumeration with no filesystem or shell work on the GUI."""
import fnmatch
import os
from pathlib import Path
import queue
import re
import threading
import time

from PySide6.QtCore import QDir,QIdentityProxyModel,Qt,QTimer,QAbstractTableModel,QModelIndex,QItemSelection,QItemSelectionModel
from PySide6.QtWidgets import (QDialog,QFileDialog,QTreeView,QVBoxLayout,QHBoxLayout,
    QLabel,QLineEdit,QPushButton,QComboBox,QAbstractItemView,QDialogButtonBox)

PATH_ROLE=int(Qt.ItemDataRole.UserRole)+1
DIR_ROLE=PATH_ROLE+1
SORT_ROLE=PATH_ROLE+2
_slots=threading.BoundedSemaphore(4)


def scan_directory(directory,cancelled,events):
    # Windows shell icon/drive providers and QFileSystemModel can make GUI
    # calls to unavailable mapped drives. Only this daemon touches a directory.
    if not _slots.acquire(blocking=False):
        events.put(('error','仍有目录在读取，请稍候后刷新，或使用本地路径。'));return
    try:
        rows=[]
        with os.scandir(directory) as entries:
            for entry in entries:
                if cancelled.is_set():return
                try:
                    is_dir=entry.is_dir(follow_symlinks=False)
                    info=entry.stat(follow_symlinks=False)
                    rows.append((entry.name,entry.path,is_dir,info.st_size,info.st_mtime))
                except OSError:continue
        if not cancelled.is_set():events.put(('rows',rows))
    except OSError as exc:
        if not cancelled.is_set():events.put(('error',f'目录未能读取：{exc}'))
    finally:_slots.release()


class EntryInfo:
    def __init__(self,path,is_dir):self._path,self._dir=path,is_dir
    def isFile(self):return not self._dir
    def isDir(self):return self._dir
    def filePath(self):return self._path


class DirectoryModel(QAbstractTableModel):
    def __init__(self,owner):super().__init__(owner);self.owner=owner;self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else 4
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:return ('名称','大小','类型','修改时间')[section]
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        name,path,is_dir,size,stamp=self.rows[index.row()]
        if role==PATH_ROLE:return path
        if role==DIR_ROLE:return is_dir
        if role==Qt.ItemDataRole.DisplayRole:
            col=index.column()
            if col==0:return name
            if col==1:return '' if is_dir else f'{size/1024:,.1f} KB'
            if col==2:return '文件夹' if is_dir else (Path(name).suffix or '文件')
            return time.strftime('%Y/%m/%d %H:%M',time.localtime(stamp))
    def replace(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()
    def sort(self,column,order=Qt.SortOrder.AscendingOrder):
        self.owner._column,self.owner._descending=column,order==Qt.SortOrder.DescendingOrder
        if hasattr(self.owner,'_entries'):self.owner.prepare_view()
    def fileInfo(self,index):
        base=self.index(index.row(),0)
        return EntryInfo(base.data(PATH_ROLE),bool(base.data(DIR_ROLE)))


class FileHeaders(QIdentityProxyModel):
    def sort(self,column,order=Qt.SortOrder.AscendingOrder):self.sourceModel().sort(column,order)


def prepare_rows(entries,patterns,column,descending,token,cancelled,events):
    """Filtering/sorting plain tuples never calls Qt comparison callbacks."""
    if cancelled.is_set():return
    matches=[re.compile(fnmatch.translate(pattern.casefold())).match for pattern in patterns]
    folders,files=[],[]
    for index,row in enumerate(entries):
        if index % 256 == 0 and cancelled.is_set():return
        if row[2]:folders.append(row)
        elif any(match(row[0].casefold()) for match in matches):files.append(row)
    def key(row):
        name,path,is_dir,size,stamp=row
        text=name.casefold()
        value=text if column==0 else size if column==1 else Path(name).suffix.casefold() if column==2 else stamp
        return value,text
    folders.sort(key=key,reverse=descending)
    if cancelled.is_set():return
    files.sort(key=key,reverse=descending)
    if not cancelled.is_set():events.put(('view',(token,folders+files)))


class LatestViewWorker:
    """One plain worker with one replaceable pending request per file dialog."""
    def __init__(self):
        self.condition=threading.Condition();self.pending=None;self.current=None
        self.closed=False;self.thread=None

    def submit(self,request):
        with self.condition:
            if self.closed:return
            if self.current is not None:self.current[-2].set()
            if self.pending is not None:self.pending[-2].set()
            self.pending=request
            if self.thread is None:
                self.thread=threading.Thread(target=self.run,name='TMA-file-sort',daemon=True)
                self.thread.start()
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.pending is not None)
                if self.closed:return
                request=self.current=self.pending;self.pending=None
            try:prepare_rows(*request)
            except Exception as exc:
                if not request[-2].is_set():request[-1].put(('view_error',(request[-3],f'列表排序失败：{exc}')))
            finally:
                with self.condition:self.current=None

    def close(self):
        with self.condition:
            self.closed=True
            if self.current is not None:self.current[-2].set()
            if self.pending is not None:self.pending[-2].set()
            self.pending=None;self.condition.notify()


class DataFileDialog(QDialog):
    def __init__(self,parent,caption,directory,filters,*,multiple=True):
        super().__init__(parent)
        self.setWindowTitle(caption);self.resize(1000,640)
        self.multiple=multiple;self._directory='';self._selected=[];self._loading=False;self._history=[]
        self._navigation=0;self._view_token=0;self._column=3;self._descending=True
        self._cancelled=threading.Event();self._events=queue.Queue()
        self._view_worker=LatestViewWorker()
        layout=QVBoxLayout(self);layout.setContentsMargins(14,14,14,14)
        top=QHBoxLayout();self.back=QPushButton('返回');self.back.clicked.connect(self.go_back);top.addWidget(self.back)
        up=QPushButton('上一级');up.clicked.connect(self.go_up);top.addWidget(up)
        top.addWidget(QLabel('文件夹：'));self.location=QLineEdit();self.location.setToolTip('输入本地、映射盘或网络共享的完整目录，按 Enter 打开。');self.location.returnPressed.connect(lambda:self.setDirectory(self.location.text()));top.addWidget(self.location,1)
        go=QPushButton('前往');go.clicked.connect(lambda:self.setDirectory(self.location.text()));top.addWidget(go);layout.addLayout(top)
        quick=QHBoxLayout()
        for label,path in (('桌面',str(Path.home()/'Desktop')),('用户目录',str(Path.home()))):
            b=QPushButton(label);b.clicked.connect(lambda checked=False,p=path:self.setDirectory(p));quick.addWidget(b)
        quick.addStretch();refresh=QPushButton('刷新');refresh.clicked.connect(lambda:self.setDirectory(self._directory));quick.addWidget(refresh);layout.addLayout(quick)
        self.model=DirectoryModel(self)
        self.headers=FileHeaders(self);self.headers.setSourceModel(self.model)
        self.tree=QTreeView();self.tree.setObjectName('treeView');self.tree.setModel(self.headers);self.tree.setRootIsDecorated(False);self.tree.setAlternatingRowColors(True);self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multiple else QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.tree.setSortingEnabled(True)
        for col,width in enumerate((430,90,90,180)):self.tree.setColumnWidth(col,width)
        self.tree.doubleClicked.connect(self.activated);self.tree.selectionModel().selectionChanged.connect(self.selection_changed);layout.addWidget(self.tree,1)
        self.feedback=QLabel();self.feedback.setWordWrap(True);layout.addWidget(self.feedback)
        row=QHBoxLayout();row.addWidget(QLabel('文件名：'));self.filename=QLineEdit();self.filename.setPlaceholderText('选择文件；Ctrl / Shift 可多选');self.filename.returnPressed.connect(self.accept);row.addWidget(self.filename,1);layout.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('文件类型：'));self.filters=QComboBox();self.filters.addItems(filters.split(';;'));self.filters.currentIndexChanged.connect(self.filter_changed);row.addWidget(self.filters,1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Open|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Open).setText('打开');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);row.addWidget(self.buttons);layout.addLayout(row)
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        self.filename.textEdited.connect(lambda:self._selected.clear())
        self.poll=QTimer(self);self.poll.setInterval(40);self.poll.timeout.connect(self.drain)
        self.sort_timer=QTimer(self);self.sort_timer.setSingleShot(True);self.sort_timer.timeout.connect(self.sort_by_time)
        self.filter_changed();self.setDirectory(directory)

    def filter_changed(self,*_):
        match=re.search(r'\(([^()]*)\)\s*$',self.filters.currentText())
        self.patterns=match.group(1).split() if match else ['*']
        if hasattr(self,'_entries'):self.prepare_view()

    def setDirectory(self,directory):
        directory=os.path.abspath(os.path.expandvars(os.path.expanduser(str(directory).strip().strip('"'))))
        if self._directory and directory!=self._directory:self._history.append(self._directory)
        self._cancelled.set();self._cancelled=threading.Event();self._events=queue.Queue()
        if hasattr(self,'_view_cancelled'):self._view_cancelled.set()
        self._navigation+=1;self._view_token+=1
        self._directory=directory;self._selected=[];self.location.setText(directory);self.filename.clear()
        if hasattr(self,'_entries'):del self._entries
        self.model.replace([]);self._loading=True;self._started=time.monotonic()
        self.feedback.setText('正在后台读取目录… 可随时取消或切换文件夹。');self.back.setEnabled(bool(self._history))
        self.buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(False)
        threading.Thread(target=scan_directory,args=(directory,self._cancelled,self._events),name='TMA-file-list',daemon=True).start()
        self.poll.start();self.sort_by_time()

    def directory(self):return QDir(self._directory)
    def selectedFiles(self):return list(self._selected)
    def selectedNameFilter(self):return self.filters.currentText()
    def viewMode(self):return QFileDialog.ViewMode.Detail
    def selectFile(self,path):
        path=str(path);self._selected=[path if os.path.isabs(path) else os.path.join(self._directory,path)];self.filename.setText(Path(path).name)
    def go_back(self):
        if not self._history:return
        target=self._history.pop();history=list(self._history);self.setDirectory(target);self._history=history;self.back.setEnabled(bool(history))
    def go_up(self):
        parent=str(Path(self._directory).parent)
        if parent!=self._directory:self.setDirectory(parent)
    def sort_by_time(self,*_):self.tree.sortByColumn(3,Qt.SortOrder.DescendingOrder)

    def drain(self):
        try:kind,value=self._events.get_nowait()
        except queue.Empty:
            if self._loading and time.monotonic()-self._started>5:self.feedback.setText('目录响应较慢，仍在后台读取。可切换路径、返回或取消；界面不会等待网络。')
            return
        if kind=='error':self._loading=False;self.poll.stop();self.feedback.setText(value);return
        if kind=='rows':self._entries=value;self.prepare_view();return
        token,rows=value
        if token!=self._view_token:return
        if kind=='view_error':
            self._loading=False;self.poll.stop();self.feedback.setText(rows);return
        self._loading=False;self.poll.stop()
        selected=set(self._selected);self.model.replace(rows)
        selection=QItemSelection()
        for i,row in enumerate(rows):
            if row[1] in selected:selection.select(self.headers.index(i,0),self.headers.index(i,3))
        self.tree.selectionModel().select(selection,QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        self.selection_changed()
        self.feedback.setText(f'{len(rows):,} 个条目 · 点击表头切换排序 · 双击文件夹进入')
        self.buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(True)

    def prepare_view(self):
        if self._view_worker.closed:return
        self._view_token+=1;self.poll.start()
        self._view_cancelled=threading.Event()
        self._view_worker.submit((self._entries,tuple(self.patterns),self._column,self._descending,self._view_token,self._view_cancelled,self._events))

    def selection_changed(self,*_):
        self._selected=[i.data(PATH_ROLE) for i in self.tree.selectionModel().selectedRows(0) if not i.data(DIR_ROLE)]
        self.filename.setText(' ; '.join(Path(p).name for p in self._selected))
    def activated(self,index):
        base=self.headers.index(index.row(),0)
        if base.data(DIR_ROLE):self.setDirectory(base.data(PATH_ROLE))
        else:self.accept()
    def accept(self):
        rows=self.tree.selectionModel().selectedRows(0)
        if not self._selected and len(rows)==1 and rows[0].data(DIR_ROLE):self.setDirectory(rows[0].data(PATH_ROLE));return
        if not self._selected:
            wanted=self.filename.text().strip().strip('"')
            for row in range(self.model.rowCount()):
                item=self.model.index(row,0);path=item.data(PATH_ROLE)
                if not item.data(DIR_ROLE) and wanted.casefold() in (Path(path).name.casefold(),str(path).casefold()):self._selected=[path];break
        if not self._selected:self.feedback.setText('请先选择文件，或等待目录读取完成后输入文件名。');return
        if not self.multiple:self._selected=self._selected[:1]
        self.stop();super().accept()
    def stop(self):self._cancelled.set();self._view_worker.close();self.poll.stop();self.sort_timer.stop()
    def reject(self):self.stop();super().reject()
    def closeEvent(self,event):self.stop();super().closeEvent(event)
