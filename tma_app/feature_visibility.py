"""Local visibility preferences for toolbar and context commands."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QTabWidget,QListWidget,QListWidgetItem,QDialogButtonBox,QLabel
from .service_jobs import ServiceJob


def load(cancelled):
    from .path_settings import _settings_data
    value = _settings_data().get('feature_visibility', {})
    if not isinstance(value, dict): return {}
    hidden = {key: value.get(key, []) for key in ('toolbar', 'context')
              if isinstance(value.get(key, []), list) and all(isinstance(v,str) for v in value.get(key, []))}
    if 'toolbar' in hidden:
        # Both toolbar rows contain the same commands at different UI scales.
        hidden['toolbar'] = list(dict.fromkeys(
            key.replace('LargeUiCommands/', 'MainToolBar/', 1) if key.startswith('LargeUiCommands/') else key
            for key in hidden['toolbar']
        ))
    return hidden


def save(cancelled, value):
    from .path_settings import _update_data
    if not cancelled.is_set():
        _update_data(lambda data: data.update(feature_visibility=value))
    return value


def context_items(menu, prefix=''):
    for action in menu.actions():
        if action.isSeparator(): continue
        name = action.objectName() or action.text().replace('&','')
        key = prefix + '/' + name
        yield menu, action, key
        submenu = action.menu()
        if submenu is not None:
            yield from context_items(submenu, key)


def context_labels(menu):
    """Display the menu's captions while keeping stable identifiers for storage."""
    labels = {}
    for parent, action, key in context_items(menu):
        caption = action.text().replace('&', '').split('\t', 1)[0].strip()
        parent_key = key.rsplit('/', 1)[0]
        label = labels[parent_key] + ' → ' + caption if parent_key in labels else caption
        labels[key] = label
        yield action, key, label


def filter_context(owner, menu):
    hidden = set(getattr(owner, '_feature_visibility', {}).get('context', []))
    for parent, action, key in list(context_items(menu)):
        if key in hidden: parent.removeAction(action)
    return menu


def toolbar_items(owner):
    from PySide6.QtWidgets import QToolBar
    for toolbar in owner.findChildren(QToolBar):
        if toolbar.objectName() not in ('MainToolBar','LargeUiCommands'): continue
        for index, action in enumerate(toolbar.actions()):
            if action.isSeparator(): continue
            widget = toolbar.widgetForAction(action)
            name = widget.objectName() if widget and widget.objectName() else action.objectName()
            key = 'MainToolBar/' + (name or str(action.data() if action.data() is not None else index))
            label = action.text() or (widget.text() if widget and hasattr(widget,'text') else '')
            if label: yield action, key, label


def apply(owner):
    hidden=set(owner._feature_visibility.get('toolbar', []))
    for action,key,_ in toolbar_items(owner): action.setVisible(key not in hidden)


def show(owner):
    dialog=QDialog(owner);dialog.setWindowTitle('显隐功能');dialog.resize(580,560)
    layout=QVBoxLayout(dialog);layout.addWidget(QLabel('勾选显示，取消勾选隐藏。顶部按钮和右键菜单分别设置。'))
    tabs=QTabWidget();layout.addWidget(tabs); lists={}
    toolbar=list(toolbar_items(owner))
    menu=owner.create_plot_context_menu(configuration=True)
    context=list(context_labels(menu))
    for group,title,items in (('toolbar','顶部功能区',toolbar),('context','图表右键菜单',context)):
        box=QListWidget();tabs.addTab(box,title);lists[group]=box
        for _,key,label in items:
            item=QListWidgetItem(label);item.setData(Qt.ItemDataRole.UserRole,key)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if key in owner._feature_visibility.get(group,[]) else Qt.CheckState.Checked)
            box.addItem(item)
    status=QLabel();layout.addWidget(status)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
    layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
    def reset():
        for box in lists.values():
            for i in range(box.count()):box.item(i).setCheckState(Qt.CheckState.Checked)
    buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(reset)
    def commit():
        value = {}
        for group, box in lists.items():
            keys = {box.item(i).data(Qt.ItemDataRole.UserRole) for i in range(box.count())}
            hidden = [key for key in owner._feature_visibility.get(group, []) if key not in keys]
            hidden.extend(box.item(i).data(Qt.ItemDataRole.UserRole) for i in range(box.count())
                          if box.item(i).checkState() == Qt.CheckState.Unchecked)
            value[group] = hidden
        buttons.setEnabled(False);status.setText('正在保存…')
        job=ServiceJob(save,(value,),dialog);dialog.job=job
        def done(event):
            if event.get('error'):status.setText(event['error']);buttons.setEnabled(True)
            else:owner._feature_visibility=value;apply(owner);dialog.accept()
            job.deleteLater()
        job.done.connect(done);job.start()
    buttons.accepted.connect(commit)
    try:
        dialog.exec()
    finally:
        menu.deleteLater()
        dialog.deleteLater()


def install(owner):
    owner._feature_visibility={};owner._visibility_revision=0
    job=ServiceJob(load,(),owner)
    def ready(event):
        if 'value' in event and owner._visibility_revision==0:owner._feature_visibility=event['value'];apply(owner)
        action.setEnabled(True)
        job.deleteLater()
    job.done.connect(ready);QTimer.singleShot(0,job.start)
    def open_dialog():
        owner._visibility_revision+=1
        show(owner)
    action = owner.settings_menu.addAction('显隐功能…', open_dialog)
    action.setEnabled(False)
