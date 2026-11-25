from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QLineEdit,QFileDialog,QMessageBox)
from PySide6.QtCore import Qt
from .service_jobs import ServiceJob


def load_mounts(cancelled):
    from .cloud_storage import settings
    return settings()['mounts']


def show(owner):
    dialog=QDialog(owner);dialog.setWindowTitle('设置备份');dialog.resize(620,260)
    layout=QVBoxLayout(dialog)
    hint=QLabel('备份数据路径、界面、显隐和渠道设置。密码仍采用 Windows 账户加密，换电脑后需重新填写。导入后请重启软件。')
    hint.setWordWrap(True);layout.addWidget(hint)
    row=QHBoxLayout();mounts=QComboBox();row.addWidget(QLabel('WebDAV 云盘'));row.addWidget(mounts,1);layout.addLayout(row)
    path=QLineEdit('/ZzzHeTMA-settings.json');layout.addWidget(path)
    status=QLabel();status.setWordWrap(True);status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(status)
    buttons=[];state={'job':None,'mounts':[]}
    def busy(value):
        for button in buttons:button.setEnabled(not value)
        mounts.setEnabled(not value);path.setEnabled(not value)
    def start(mode,cloud):
        if state['job'] is not None:return
        mount=None
        if cloud:
            index=mounts.currentIndex()
            if index<0 or index>=len(state['mounts']):status.setText('请先在云盘设置中挂载 WebDAV');return
            mount=state['mounts'][index];target=path.text().strip()
            if not target.startswith('/') or target.endswith('/'):status.setText('请输入完整云端文件路径，例如 /ZzzHeTMA-settings.json');return
        else:
            chooser=QFileDialog.getSaveFileName if mode=='export' else QFileDialog.getOpenFileName
            target,_=chooser(dialog,'设置备份','ZzzHeTMA-settings.json','JSON (*.json)')
            if not target:return
        if mode=='import' or cloud:
            text='导入会覆盖当前设置，是否继续？' if mode=='import' else '导出会覆盖云端同路径文件，是否继续？'
            if QMessageBox.question(dialog,'设置备份',text)!=QMessageBox.StandardButton.Yes:return
        from .settings_backup import run
        job=ServiceJob(run,(mode,target,mount),dialog);state['job']=job;busy(True);status.setText('正在处理…')
        def done(event):
            state['job']=None;busy(False);status.setText(event.get('error') or event['value']);job.deleteLater()
        job.done.connect(done);job.start()
    row=QHBoxLayout()
    for label,mode,cloud in [('导出文件','export',False),('导入文件','import',False),('导出到 WebDAV','export',True),('从 WebDAV 导入','import',True)]:
        button=QPushButton(label);button.clicked.connect(lambda checked=False,m=mode,c=cloud:start(m,c));buttons.append(button);row.addWidget(button)
    layout.addLayout(row)
    close=QPushButton('关闭');close.clicked.connect(dialog.reject);layout.addWidget(close)
    loader=ServiceJob(load_mounts,(),dialog)
    def loaded(event):
        if 'error' in event:status.setText(event['error'])
        else:
            state['mounts']=event['value']
            for mount in state['mounts']:mounts.addItem(mount['name'])

    loader.done.connect(loaded);loader.start()
    def cancel():
        loader.cancel()
        if state['job'] is not None:state['job'].cancel()
    dialog.finished.connect(cancel)
    dialog.exec();dialog.deleteLater()
