"""User menu and matching local-login/membership windows."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox

from . import user_account as account


class UserDialog(QDialog):
    def __init__(self, owner, *, membership=False):
        super().__init__(owner)
        self.owner = owner; self.membership = membership
        self.setObjectName('UserMembershipDialog' if membership else 'UserLoginDialog')
        self.setWindowTitle('我的会员' if membership else '用户登录')
        self.setMinimumWidth(480)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        intro = QLabel('本机昵称登录。会员激活后显示红色昵称。' if not membership else '授权绑定本机机器码；机器码不变，激活长期有效。')
        intro.setWordWrap(True); layout.addWidget(intro)
        form = QFormLayout(); layout.addLayout(form)
        self.nickname = QLineEdit(); self.nickname.setMaxLength(24)
        self.nickname.setPlaceholderText('填写本机使用的昵称')
        self.nickname_label = QLabel()
        self.nickname_label.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow('昵称', self.nickname_label if membership else self.nickname)
        self.state = QLabel(); form.addRow('会员状态', self.state)
        self.machine = QLineEdit(account.machine_code()); self.machine.setReadOnly(True)
        self.machine.setToolTip('本机机器码。激活后与此机器码绑定；昵称修改不会解除激活。')
        form.addRow('机器码', self.machine)
        self.activated = QLabel(); form.addRow('激活时间', self.activated)
        self.code = QLineEdit(); self.code.setMaxLength(128); self.code.setPlaceholderText('请输入销售人员提供的授权码')
        self.code.setToolTip('输入授权码，在本机激活会员。成功后只增加红色昵称，不改变分析功能。')
        self.code_label = QLabel('授权码'); form.addRow(self.code_label, self.code)
        self.code.setVisible(membership); self.code_label.setVisible(membership)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        controls = QHBoxLayout(); controls.addStretch(); layout.addLayout(controls)
        self.submit = QPushButton('激活授权' if membership else '登录'); self.submit.setDefault(True)
        self.submit.clicked.connect(self.submit_values); controls.addWidget(self.submit)
        close = QPushButton('关闭'); close.clicked.connect(self.reject); controls.addWidget(close)
        self.refresh()

    def refresh(self):
        data = account.load_account(); member = account.is_member(data)
        self.nickname.setText(data.get('nickname', ''))
        self.nickname_label.setText(data.get('nickname') or '未登录')
        self.nickname_label.setStyleSheet('color:#d62839; font-weight:bold;' if member else '')
        self.state.setText('永久激活' if member else '未激活')
        self.activated.setText(data.get('activated_at', '—') if member else '—')
        if self.membership:
            self.submit.setVisible(not member); self.code.setVisible(not member); self.code_label.setVisible(not member)

    def submit_values(self):
        try:
            if self.membership:
                account.activate(self.code.text()); self.code.clear()
                self.feedback.setText('授权成功，永久激活。')
            else:
                account.login(self.nickname.text())
                self.feedback.setText('登录成功，昵称已保存。')
            self.refresh(); self.owner.refresh_user_badge()
        except (ValueError, OSError) as exc:
            self.feedback.setText(str(exc))


def install(owner):
    menu = owner.menuBar().addMenu('用户'); menu.setToolTipsVisible(True); owner.user_menu = menu
    owner.user_actions = {}
    for key, caption, tip in (
        ('login', '登录', '设置并保存本机使用的昵称；登录后可在“我的会员”激活授权。'),
        ('membership', '我的会员', '查看昵称、机器码及会员状态；输入授权码绑定当前机器，成功后显示永久激活与红色昵称。'),
        ('purchase', '购买会员', '显示购买会员的销售联系提示。')):
        action = menu.addAction(caption); action.setToolTip(tip); action.setStatusTip(tip)
        action.setObjectName('User'+key.title()); owner.user_actions[key] = action
        action.triggered.connect(lambda checked=False, value=key: show(owner, value))
    owner.user_badge = QLabel(); owner.user_badge.setObjectName('UserNickname')
    owner.user_badge.setTextFormat(Qt.TextFormat.PlainText)
    owner.user_badge.setContentsMargins(8,0,8,0)
    owner.user_badge.setMaximumWidth(116)
    toolbar = getattr(owner, 'command_toolbar', getattr(owner, 'classic_toolbar', None))
    if toolbar is not None:
        before = next((a for a in toolbar.actions() if toolbar.widgetForAction(a) is owner.share_button), None)
        if before is not None: toolbar.insertWidget(before, owner.user_badge)
        else: toolbar.addWidget(owner.user_badge)
    else: owner.statusBar().addPermanentWidget(owner.user_badge)
    owner.refresh_user_badge = lambda: refresh_badge(owner)
    refresh_badge(owner)
    # Retain native menu actions as well as their menus. Temporary wrappers
    # returned by QMenuBar.actions()/QAction.menu() can otherwise invalidate a
    # menu when a Python iterator releases the QAction wrappers (PySide 6.10).
    owner._root_menu_actions = list(owner.menuBar().actions())


def refresh_badge(owner):
    data = account.load_account(); member = account.is_member(data)
    nickname = data.get('nickname') or '未登录'
    owner.user_badge.setText(owner.user_badge.fontMetrics().elidedText(nickname, Qt.TextElideMode.ElideRight, 100))
    owner.user_badge.setStyleSheet('color:#d62839; font-weight:bold;' if member else 'color:#89748f;')
    owner.user_badge.setToolTip(f'{nickname}\n'+('永久激活 · 会员昵称' if member else '可通过“用户 → 登录 / 我的会员”设置昵称和激活授权。'))


def show(owner, kind):
    if kind == 'purchase':
        QMessageBox.information(owner, '购买会员', '请联系销售人员'); return
    dialogs = getattr(owner, '_user_dialogs', None)
    if dialogs is None: dialogs = owner._user_dialogs = {}
    existing = dialogs.get(kind)
    if existing is not None and existing.isVisible(): existing.raise_(); return existing
    dialog = UserDialog(owner, membership=kind == 'membership'); dialogs[kind] = dialog
    if existing is not None: existing.deleteLater()
    dialog.show(); return dialog
