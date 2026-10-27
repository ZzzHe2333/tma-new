"""Pixel-framed local achievement wall and a non-activating coin toast."""
from __future__ import annotations

from collections import OrderedDict
import math
import hashlib
import os
from pathlib import Path
import queue
import threading
import weakref

from PySide6.QtCore import QObject, QTimer, Qt, Signal, QRectF, QElapsedTimer, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QGridLayout, QComboBox, QMessageBox)

from .achievements import CATALOG, BY_KEY, TIERS, empty, disk_worker


def frame(p, rect, tier, unlocked=True):
    """Bevel direction, rather than colour alone, distinguishes locked tiles."""
    r = QRectF(rect)
    base = QColor(tier.base if unlocked else '#e1dce3')
    light = QColor(tier.light if unlocked else '#fcf9fc')
    dark = QColor(tier.dark if unlocked else '#a99dac')
    p.fillRect(r, base)
    p.setPen(QPen(light if unlocked else dark, 3))
    p.drawLine(r.topLeft(), r.topRight()); p.drawLine(r.topLeft(), r.bottomLeft())
    p.setPen(QPen(dark if unlocked else light, 3))
    p.drawLine(r.bottomLeft(), r.bottomRight()); p.drawLine(r.topRight(), r.bottomRight())
    p.fillRect(r.adjusted(5, 5, -5, -5), QColor('#fff9ee' if unlocked else '#cfc8d3'))
    if unlocked:
        p.fillRect(QRectF(r.left()+7, r.top()+7, 3, 3), light)
        p.fillRect(QRectF(r.right()-10, r.bottom()-10, 3, 3), dark)


def glyph(p, rect, name, enabled=True):
    """Original 16x16 pixel pictograms, painted without external game assets."""
    p.save(); p.translate(rect.topLeft()); p.scale(rect.width()/16, rect.height()/16)
    ink = QColor('#66536d' if enabled else '#928a97')
    accent = QColor('#78baa5' if enabled else '#aaa3ae')
    gold = QColor('#ebbf59' if enabled else '#b4a9b2')
    def block(x, y, w, h, color=ink): p.fillRect(QRectF(x, y, w, h), color)
    def line(x1, y1, x2, y2, color=ink):
        p.setPen(QPen(color, 1.2)); p.drawLine(QPointF(x1,y1),QPointF(x2,y2))
    if name == 'picture':
        block(1,2,14,12); block(2,3,12,10,QColor('#f3e5ee')); block(10,4,2,2,gold)
        for x,y in ((3,10),(5,8),(7,10),(9,9),(11,11)): block(x,y,2,2,accent)
    elif name == 'folder':
        block(1,3,6,3,gold);block(1,5,14,9,gold);block(2,7,12,6,QColor('#f8dda0'))
        block(4,8,5,1);block(4,10,7,1)
    elif name == 'lens':
        block(2,2,8,2);block(2,2,2,8);block(2,8,8,2);block(8,2,2,8)
        block(4,4,4,4,accent);block(10,10,2,2);block(12,12,3,3,gold)
    elif name == 'curves':
        block(1,1,1,14);block(1,14,14,1)
        for x,y in ((3,10),(5,8),(7,4),(9,5),(11,9)): block(x,y,2,2,accent)
        for x,y in ((3,12),(5,10),(7,8),(9,9),(11,11)): block(x,y,2,2,gold)
    elif name == 'blocks':
        for x,y in ((2,2),(9,2),(2,9),(9,9)):
            block(x,y,5,5);block(x+1,y+1,3,3,accent if y==2 else gold)
    elif name == 'table':
        block(1,2,14,12);block(2,3,12,3,accent)
        for y in (7,10):
            for x in (2,6,10):block(x,y,3,2,QColor('#fff1d8'))
    elif name == 'page':
        block(3,1,10,14);block(4,2,8,12,QColor('#fff1d8'))
        for y in (5,8,11):block(5,y,6,1,accent)
    elif name == 'mail':
        block(1,4,14,10);block(2,5,12,8,QColor('#f4dfc9'))
        line(2,5,8,10);line(8,10,14,5);block(10,1,4,2,accent)
    elif name == 'balance':
        block(7,2,2,12);block(4,13,8,2);block(1,4,14,1)
        for x in (3,12):
            line(x,5,x-2,9);line(x,5,x+2,9);block(x-2,9,5,2,accent)
    else:
        block(5,2,6,12,gold);block(2,5,12,6,gold);block(6,4,2,8,QColor('#fff1ac'))
    p.restore()


def small_icon():
    pixmap = QPixmap(32,32); pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap); frame(p,QRectF(2,2,28,28),TIERS[4]);glyph(p,QRectF(8,8,16,16),'coin');p.end()
    return QIcon(pixmap)


class Badge(QWidget):
    def __init__(self, achievement, tier, parent):
        super().__init__(parent)
        self.achievement,self.tier,self.unlocked=achievement,tier,False
        self.setFixedSize(52,72)

    def apply(self, state):
        n=state['counts'][self.achievement.key];self.unlocked=n>=self.tier.threshold
        stamp=state['earned'].get(self.achievement.key+':'+self.tier.key,'')
        self.setToolTip(f'{self.tier.name}框 · {self.achievement.name}\n{self.achievement.description}\n'
            f'累计 {self.tier.threshold:,} {self.achievement.unit} · 当前 {n:,}\n'
            + (('已获得'+(' · '+stamp.replace('T',' ').replace('+00:00',' UTC') if stamp else '')) if self.unlocked else '尚未获得 · 凹入框'))
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);frame(p,QRectF(4,3,44,44),self.tier,self.unlocked)
        glyph(p,QRectF(14,13,24,24),self.achievement.glyph,self.unlocked)
        p.setPen(QColor('#5c4b65' if self.unlocked else '#99909f'));p.setFont(QFont('Microsoft YaHei',8))
        p.drawText(QRectF(0,50,52,20),Qt.AlignmentFlag.AlignCenter,self.tier.name);p.end()


class AchievementCard(QWidget):
    def __init__(self,achievement,parent):
        super().__init__(parent);self.achievement=achievement
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setObjectName('AchievementCard')
        self.setStyleSheet('QWidget#AchievementCard {background:#fffcff;border:1px solid #e1d3e7;border-radius:8px;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(14,12,14,10);layout.setSpacing(5)
        self.title=QLabel(achievement.name);self.title.setStyleSheet('font-weight:bold;font-size:15px;color:#665071;');layout.addWidget(self.title)
        desc=QLabel(achievement.description);desc.setWordWrap(True);desc.setMinimumHeight(34);layout.addWidget(desc)
        self.progress=QLabel();self.progress.setObjectName('muted');layout.addWidget(self.progress)
        row=QHBoxLayout();row.setSpacing(2);self.badges=[]
        for tier in TIERS:
            badge=Badge(achievement,tier,self);self.badges.append(badge);row.addWidget(badge)
        row.addStretch();layout.addLayout(row)

    def apply(self,state):
        n=state['counts'][self.achievement.key]
        next_tier=next((t for t in TIERS if n<t.threshold),None)
        self.progress.setText(f'累计 {n:,} {self.achievement.unit}  ·  '+(f'下一级：{next_tier.name}框 {n:,} / {next_tier.threshold:,}' if next_tier else '全部等级已点亮'))
        for badge in self.badges:badge.apply(state)


class AchievementWall(QDialog):
    def __init__(self,owner,controller):
        super().__init__(owner);self.controller=controller
        self.setWindowTitle('成就展示墙 · ZzzHe TMA Analysis');self.setWindowIcon(small_icon())
        from .theme import CUTE_STYLE
        self.setStyleSheet(CUTE_STYLE)
        available=owner.screen().availableGeometry()
        self.resize(min(970,available.width()-60),min(770,available.height()-70))
        layout=QVBoxLayout(self);layout.setContentsMargins(18,16,18,14)
        header=QHBoxLayout();title=QLabel('小小实验，大大成就');title.setStyleSheet('font-size:23px;color:#765a82;font-weight:bold;');header.addWidget(title);header.addStretch()
        self.filter=QComboBox();self.filter.addItems(['全部成就','已获得等级的成就','尚未获得等级的成就']);self.filter.currentIndexChanged.connect(self.refresh);header.addWidget(self.filter);layout.addLayout(header)
        self.summary=QLabel('正在读取本地成就…');layout.addWidget(self.summary)
        intro=QLabel('每项成就都有 7 个等级：木 1 → 石 10 → 铜 100 → 铁 300 → 金 1,000 → 钻石 3,000 → 下界合金 10,000。\n亮起的凸框表示已获得，灰色凹框表示未获得；悬停可查看条件和获得时间。');intro.setWordWrap(True);intro.setObjectName('muted');layout.addWidget(intro)
        scroll=QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll,1)
        self.content=QWidget();self.grid=QGridLayout(self.content);self.grid.setSpacing(12);self.grid.setContentsMargins(10,10,10,10);scroll.setWidget(self.content)
        self.cards=[AchievementCard(a,self.content) for a in CATALOG];self._columns=0
        self.notice=QLabel();self.notice.setWordWrap(True);self.notice.setObjectName('muted');layout.addWidget(self.notice)
        footer=QHBoxLayout();clear=QPushButton('清除统计…');clear.setObjectName('ClearAchievements');clear.setToolTip('仅清除本机成就计数、获得时间和边框进度，不删除设置、样品或分析结果。');clear.clicked.connect(self.clear_statistics);footer.addWidget(clear);footer.addStretch()
        close=QPushButton('关闭');close.clicked.connect(self.close);footer.addWidget(close);layout.addLayout(footer)
        controller.changed.connect(self.refresh);self.refresh()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'cards'):self.arrange()

    def arrange(self):
        columns=2 if self.width()>=880 else 1
        for card in self.cards:self.grid.removeWidget(card)
        visible=[c for c in self.cards if not c.isHidden()]
        for i,card in enumerate(visible):self.grid.addWidget(card,i//columns,i%columns)
        self.grid.setColumnStretch(0,1);self.grid.setColumnStretch(1,1 if columns==2 else 0)

    def refresh(self):
        state=self.controller.state;mode=self.filter.currentIndex()
        count=len(state['earned']);total=len(CATALOG)*len(TIERS)
        self.summary.setText(f'已获得 {count} / {total} 个成就框  ·  已点亮 {sum(n>0 for n in state["counts"].values())} / {len(CATALOG)} 项成就')
        for card in self.cards:
            n=state['counts'][card.achievement.key];card.apply(state)
            card.setVisible(mode==0 or (mode==1 and n>0) or (mode==2 and n<TIERS[-1].threshold))
        self.arrange()
        self.notice.setText(self.controller.error or ('统计仅保存在本机，不记录文件名或样品数据。\n'+self.controller.location))
        self.findChild(QPushButton,'ClearAchievements').setEnabled(self.controller.loaded)

    def clear_statistics(self):
        answer=QMessageBox.question(self,'清除本地成就统计','清除所有成就计数、获得时间和已点亮的框？\n样品、分析结果、设置和会员状态都会保留。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:self.controller.reset()


class AchievementToast(QWidget):
    def __init__(self,owner,key,tier,done):
        super().__init__(owner,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.a=BY_KEY[key];self.tier=tier;self.done=done;self.clock=QElapsedTimer()
        self.resize(400,175);self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)

    def start(self):
        area=self.parentWidget().screen().availableGeometry()
        self.move(area.right()-self.width()-18,area.bottom()-self.height()-12)
        self.clock.start();self.show();self.timer.start()

    def tick(self):
        if self.clock.elapsed()>=4600:
            self.timer.stop();self.close();self.done();self.deleteLater()
        else:self.update()

    def paintEvent(self,event):
        elapsed=self.clock.elapsed()/1000;progress=min(1,elapsed/.25)
        p=QPainter(self);p.setOpacity(min(1,(4.6-elapsed)/.3));p.translate(0,(1-progress)*48)
        # Soft pastel card, with material-coloured frame and pixel bevel.
        r=QRectF(4,49,392,119);frame(p,r,self.tier)
        p.fillRect(r.adjusted(6,6,-6,-6),QColor('#fff8fc'))
        frame(p,QRectF(20,76,60,60),self.tier);glyph(p,QRectF(32,88,36,36),self.a.glyph)
        p.setPen(QColor('#9a713c'));p.setFont(QFont('Microsoft YaHei',9));p.drawText(QRectF(94,62,290,22),'成就已解锁  ·  '+self.tier.name+'框')
        p.setPen(QColor('#5e466b'));p.setFont(QFont('Microsoft YaHei',12,QFont.Weight.Bold));p.drawText(QRectF(94,88,286,29),self.a.name)
        p.setPen(QColor('#86758d'));p.setFont(QFont('Microsoft YaHei',9));p.drawText(QRectF(94,122,286,24),f'累计完成 {self.tier.threshold:,} {self.a.unit}')
        # An original deterministic coin fountain. No audio, focus or input grab.
        if elapsed<2.6:
            for i in range(14):
                t=elapsed-(i%4)*.065
                if not 0<t<1.9:continue
                vx=(i%7-3)*40;vy=-125-(i%3)*18
                x=51+vx*t;y=90+vy*t+100*t*t
                p.save();p.setOpacity(max(0,1-t/1.9));w=max(2,abs(math.cos(t*9+i))*10)
                p.fillRect(QRectF(x-w/2,y,w,12),QColor('#a77622'));p.fillRect(QRectF(x-w/2+1,y+1,max(1,w-2),9),QColor('#f4cb4e'))
                p.fillRect(QRectF(x,y+2,1,5),QColor('#fff6b2'));p.restore()
        p.end()


def common_achievement_path(primary):
    """Windows' shared app-data directory is a C: fallback, never the checkout."""
    drive=os.environ.get('SystemDrive','C:')
    base=Path(os.environ.get('ProgramData',drive+'/ProgramData'))
    if base.drive.casefold()!=drive.casefold():base=Path(drive+'/ProgramData')
    identity=hashlib.sha256(os.path.normcase(os.path.abspath(primary)).encode('utf-8')).hexdigest()[:16]
    return base/'ZzzHeTMA'/identity/'achievements.json'


def _storage(primary,commands,events):
    # Statistics belong to the C: profile, never to a project/release folder.
    # Legacy portable data may be imported once, but all new writes go here.
    from .ui_size import fallback_paths
    secondary=common_achievement_path(primary)
    try:
        if not primary.exists() and not secondary.exists():
            from .achievements import load
            legacy=[p for p in fallback_paths(primary) if p!=primary]
            if legacy:
                data,location=load(legacy)
                if location.exists():
                    from .atomic_files import write_json
                    try:write_json(primary,data)
                    except OSError:write_json(secondary,data)
    except (OSError,ValueError,TypeError) as exc:
        events.put(('error','旧成就迁移到用户配置目录未完成：'+str(exc)))
    disk_worker([primary,secondary],secondary,commands,events)


class AchievementController(QObject):
    changed=Signal()

    def __init__(self,primary,parent):
        super().__init__(parent);self.state=empty();self.location=str(primary);self.error='';self.loaded=False
        self.commands=queue.Queue();self.events=queue.Queue();self.windows=weakref.WeakSet();self.owner=None
        self.waiting=OrderedDict();self.toast=None;self.stopped=False;self.epoch=0
        self.thread=threading.Thread(target=_storage,args=(primary,self.commands,self.events),name='TMA-achievements',daemon=True)
        self.timer=QTimer(self);self.timer.setInterval(60);self.timer.timeout.connect(self.drain)
        self.thread.start();self.timer.start()

    def record(self,key,amount,owner):
        if self.stopped or getattr(owner,'_closing',False):return
        self.owner=weakref.ref(owner);self.commands.put(('record',key,amount))

    def reset(self):
        self.waiting.clear()
        if self.toast is not None:
            self.toast.timer.stop();self.toast.close();self.toast.deleteLater();self.toast=None
        self.epoch+=1;self.error='';self.commands.put(('reset',self.epoch))

    def drain(self):
        changed=False
        for _ in range(256):
            try:item=self.events.get_nowait()
            except queue.Empty:break
            if item[0]=='error':self.error=item[1];changed=True
            else:
                if item[4] < self.epoch: continue
                self.state,self.location=item[1],item[3];self.loaded=True;changed=True
                for key,tier in item[2]:self.waiting[key]=tier
        if changed:self.changed.emit()
        if self.toast is None and self.waiting and self.owner is not None:
            owner=self.owner()
            if owner is None or getattr(owner,'_closing',False):self.waiting.clear();return
            active=QApplication.activeWindow()
            if not owner.isVisible() or owner.isMinimized() or active is None:return
            if active is not owner and not owner.isAncestorOf(active):return
            key,tier=self.waiting.popitem(last=False)
            self.toast=AchievementToast(owner,key,next(t for t in TIERS if t.key==tier),self.toast_done);self.toast.start()

    def toast_done(self):self.toast=None

    def detach(self,window):
        self.windows.discard(window)
        if self.toast is not None and self.toast.parentWidget() is window:
            self.toast.timer.stop();self.toast.close();self.toast.deleteLater();self.toast=None
        if not self.windows:
            self.stopped=True;self.waiting.clear();self.timer.stop();self.commands.put(('stop',))
            # Local-only background writes get a brief opportunity to finish;
            # quitting never waits for a network source or an unbounded join.
            self.thread.join(.2)


def record(owner,key,amount=1):
    controller=getattr(owner,'achievement_controller',None)
    if controller is not None:controller.record(key,amount,owner)


def install(owner):
    from .path_settings import config_path
    application=QApplication.instance();primary=config_path().with_name('achievements.json')
    controllers=getattr(application,'_achievement_controllers',{})
    key=str(primary);controller=controllers.get(key)
    if controller is None or controller.stopped:
        controller=AchievementController(primary,application);controllers[key]=controller
        application._achievement_controllers=controllers
    owner.achievement_controller=controller;controller.windows.add(owner)
    def show_wall():
        wall=getattr(owner,'achievement_wall',None)
        if wall is None:
            wall=owner.achievement_wall=AchievementWall(owner,controller)
        wall.show();wall.raise_();wall.activateWindow();return wall
    owner.show_achievements=show_wall
    menu=owner.menuBar().addMenu('成就');menu.addAction(small_icon(),'成就展示墙…',show_wall)
    toolbar=getattr(owner,'classic_toolbar',None)
    button=QPushButton('成就',owner);button.setIcon(small_icon());button.setToolTip('打开本机成就展示墙：查看 9 项成就和 7 种材质边框、累计次数与获得条件，也可清除统计。')
    button.clicked.connect(show_wall)
    if toolbar is not None:toolbar.addWidget(button)
    else:owner.statusBar().addPermanentWidget(button)
    owner.achievement_button=button
