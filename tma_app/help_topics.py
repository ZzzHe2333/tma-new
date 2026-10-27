"""Offline operating guide; imported only when the user opens teaching/help."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout,
)

from . import APP_NAME


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    keywords: str
    body: str

    def matches(self, query):
        text = unescape(re.sub(r'<[^>]+>', ' ', self.body))
        haystack = f'{self.title} {self.keywords} {text}'.casefold()
        return all(word in haystack for word in query.casefold().split())


TOPICS = (
    Topic('start', '快速上手 · 从打开到出图', '入门 教学 新手 使用步骤 导入 .001 .007', '''
<p>按下面这条顺序操作，即可完成一次两点测量并导出图片。教学窗口可放在旁边，一边看一边操作。</p>
<ol>
<li><b>打开数据：</b>点击左上角文件夹图标，或“文件 → 打开”，选择 .001、.002、.007 等数据文件；也可以把文件拖进主窗口。</li>
<li><b>选中要分析的图：</b>多文件时，先点击目标图窗口。单图与叠图都以当前活动图为操作对象。</li>
<li><b>进入测量：</b>在曲线框内的空白处右键，选择“尺寸变化”或“信号变化”。</li>
<li><b>调整两点：</b>左右拖动红色十字；需要精确温度时，再右键选择“编辑…”。</li>
<li><b>确定结果：</b>在选点状态下右键 → “确定”，保留结果。查看 T1、T2、H；具体内容由所选分析决定。</li>
<li><b>整理后出图：</b>拖动文字避开曲线，按需调整字号，再用“文件 → 导出绘图”保存图片。</li>
</ol>
<p><b>没有打开文件时：</b>先完成第 1 步。空白界面还没有可编辑的文件信息或可测量的曲线。</p>
<p><b>选择文件：</b>详细列表默认按修改时间降序显示，最新在前。每次启动首次从设置的默认目录打开，之后沿用本次最近选定文件所在目录；取消不会改变它，重启回到默认目录。</p>
<p><b>关闭程序：</b>点击主窗口右上角 × 直接退出，不询问保存。需要保留图片、表格或分析时，请先主动导出或保存分析文件；本次打开的数据不会自动保存。</p>
<p>继续阅读：<a href="help:right_click">右键在哪里点</a> · <a href="help:changes">两点变化量</a> · <a href="help:export">导出图片</a></p>'''),
    Topic('right_click', '右键与选点 · 确定、编辑、取消', '鼠标 光标 手动温度 十字 点1 点2 快捷键', '''
<p><b>右键出现什么，取决于你点在哪里，以及当前是否正在选点。</b></p>
<table cellpadding="8" cellspacing="1" width="100%">
<tr bgcolor="#f0e5f7"><th>位置 / 状态</th><th>操作</th></tr>
<tr><td>曲线框内空白处，尚未开始选点</td><td>打开常规右键菜单，选择尺寸变化、信号最大、信号变化等。</td></tr>
<tr bgcolor="#faf4fb"><td>正在调整红色分析点</td><td>打开选点菜单，包含“确定”“编辑…”“取消”和点编号；此时不显示常规分析菜单。</td></tr>
<tr><td>坐标轴数字、轴标题或轴线</td><td>打开重定刻度窗口，可输入轴的起止值与间隔。</td></tr>
<tr bgcolor="#faf4fb"><td>已经确定的结果文字</td><td>调整该文字的字号、粗体、斜体和显隐，也可重新调整结果。</td></tr>
</table>
<h3>选点的完整步骤</h3>
<ol><li>先在框内空白处右键，选择所需分析。</li>
<li>用左键按住红色十字，沿曲线左右拖动。通过右键菜单“点 1”“点 2”等可选择当前点。</li>
<li>需要精确值：右键 → “编辑…”，输入温度后确认。若 X 轴已改为时间或其他信号，输入的是当前 X 坐标，并非温度。</li>
<li>右键 → “确定”完成；右键 → “取消”放弃本次尚未确认的调整。</li></ol>
<p>键盘辅助：选点时可用左右方向键微调；按住 Ctrl 或 Shift 时步幅更大。</p>
<p><b>为什么右键没有出现尺寸变化？</b>如果还在选点，先确定或取消；如果点到了文字或坐标轴，改在曲线框内的空白处右键。</p>
<p><a href="help:changes">继续：尺寸变化、信号变化与高度差</a></p>'''),
    Topic('changes', '尺寸变化、信号变化与高度差', 'T1 T2 H delta 变化量 两点 温度 高度', '''
<p>这些功能通过曲线上的两个点读取起止坐标与信号差。操作前先检查当前图和 Y 轴信号、单位是否正确。</p>
<ol><li>在目标图空白处右键，选择“尺寸变化”“信号变化”或“高度差”。</li>
<li>拖动两个红色十字，让点 1、点 2 分别落在希望比较的位置；也可右键 → “编辑…”手动输入坐标。</li>
<li>右键 → “确定”，图上保留对应结果。温度横轴下，两点温度会作为 T1、T2 显示；H 为所选点的信号差，单位由当前尺寸信号决定。</li>
<li>若文字重叠，直接用左键分别拖动 T1、T2、H。右键某一个文字，可单独改字号或隐藏。</li></ol>
<p><b>核对顺序：</b>选对文件 → 选对信号和单位 → 调整两点 → 确定 → 核对结果。差值方向与点顺序、所选方法有关，不要把带符号的变化量一律当作正的峰高。</p>
<p>已确定后需要修改分析点：右键结果文字 → “调整结果”，重新调点并确定。只想移动文字时直接拖动文字即可。</p>
<p>玻璃化转变采用另一种分析：拟合相关区间并给出转变结果，不以尺寸变化的 T1、T2、H 标签规则解释。</p>
<p><a href="help:labels">继续：独立调整结果文字</a> · <a href="help:export">整理好后导出图片</a></p>'''),
    Topic('maximum', '信号最大 · 自动找峰后手动调整', '最大值 峰顶 温度 单点', '''
<ol><li>选中目标图，在框内空白处右键 → “信号最大”。</li>
<li>分析点初始位于曲线最大值处。可以沿曲线左右拖动，或右键 → “编辑…”输入具体 X 坐标。</li>
<li>右键 → “确定”，保留该点的温度标注。</li>
<li>需要调整标注位置时，左键拖动文字；需要重新选点时，右键该文字 → “调整结果”。</li></ol>
<p>把分析点从峰顶移走后，标注对应的是移动后的坐标；请根据实际选点解释结果。</p>
<p><a href="help:right_click">查看选点菜单说明</a></p>'''),
    Topic('labels', '结果文字 · 拖动、字号与显隐', 'T1 T2 H 字体 多个信息点 独立调整 恢复 标注', '''
<ol><li>先用右键 → “确定”结束选点。</li>
<li>左键按住目标文字，拖到合适位置；T1、T2、H 等文字可以分别移动。</li>
<li>在目标文字上右键 → “字号”，选择大小；也可以切换粗体、斜体。</li>
<li>选择“隐藏此文字”只隐藏当前文字；“文字显隐”子菜单可分别勾选同一结果中的其他文字。</li>
<li>恢复被隐藏的文字：在图空白处右键 → “分析文字显隐”，找到对应结果并重新勾选该文字。</li></ol>
<p>“隐藏结果”作用于整条分析结果；“删除结果”会移除该结果。请根据需要选择。</p>
<p>导出的图片包含当前显示的结果和标注。隐藏的文字不会出现在图片中。</p>
<p><a href="help:export">继续：导出图片</a></p>'''),
    Topic('file_information', '编辑 → 文件信息', '样品 操作者 方法 备注 尺寸 保存 文件名 文件路径', '''
<p><b>用途：</b>查看当前文件的采集信息，编辑样品名、操作者、方法、备注，以及支持的 TMA 原始尺寸。</p>
<ol><li>先打开一个数据文件，并点击要编辑的图窗口；叠图中应先明确选中要编辑的曲线，或回到该文件的普通图。</li>
<li>点击“编辑 → 文件信息”。窗口显示运行日期、读取点数、使用点数及可识别的其他源信息。</li>
<li>在样品、操作者、方法、备注等输入框中修改内容。点击“确定”应用；“取消”或右上角 × 放弃本次草稿。</li>
<li>需要下次继续使用修改：使用“文件 → 保存分析 → 分析和数据”保存为本应用的 .tmas 分析文件；以后打开该分析文件恢复。</li></ol>
<h3>哪些内容能改</h3>
<ul><li>样品名最多 32 字，操作者 25 字，备注 64 字；这些输入框为单行。</li>
<li>仅修改文字时保留已有处理与分析。</li>
<li>修改 TMA 尺寸会重新读取同一源文件，并清除该文件当前处理与相关分析。尺寸单位为 mm；0 表示未指定，Alpha 分析可能再次要求实测尺寸。</li>
<li>运行日期、点数等采集信息供查看；无法识别的项显示“—”。放热方向、池常数重算等未开放项会禁用。</li></ul>
<p><b>保存位置：</b>这些修改保存在本应用分析文件中，不改写原始 .001 / .007 文件。重新导入原始文件仍读取原始信息；修改样品名也不会更改磁盘文件名或真实路径。</p>
<p><a href="help:start">还没打开文件？查看快速上手</a> · <a href="help:export">修改标题信息后导出图片</a></p>'''),
    Topic('export', '导出图片 · 单图与叠图', 'PNG SVG PDF TIFF tif 保存 图片 出图 分辨率 白边 文件名 分享 打印', '''
<p><b>入口：</b>“文件 → 导出绘图”，随后出现“导出图像”保存窗口。先选中要输出的图窗口；单图与叠图按同一流程操作。</p>
<ol><li><b>确定分析：</b>如果还有红色点正在编辑，先右键 → “确定”。</li>
<li><b>整理图面：</b>检查曲线、坐标范围、标题、图例和文字；把需要保留的标注打开，并拖到合适位置。</li>
<li><b>选择格式：</b>点击“文件 → 导出绘图”，在保存窗口选择位置、文件名及格式。一般分享选 PNG；需要矢量输出时可选 SVG 或 PDF；也支持 TIFF。</li>
<li><b>保存：</b>文件名默认取当前样本的源文件名（不含原后缀）。建议保留与所选格式一致的扩展名，例如“20261017-5#.png”。</li>
<li><b>检查输出：</b>到保存位置打开图片，确认温度、单位及文字齐全。导出后窗口底部会显示保存位置。</li></ol>
<h3>图片包含什么</h3>
<ul><li>当前活动图上的可见曲线、结果文字、批注、坐标和图例；叠图也可以直接导出。</li>
<li>外围保留白边，位图按 300 dpi 输出，页脚为“Power By ZzzHe”。</li>
<li>如果在曲线图选项中设置了专用导出标题，输出按该标题配置显示，可能与屏幕上的源路径标题不同。</li></ul>
<p>图片用于展示；要保留可再次编辑的分析，应另外保存 .tmas 分析文件。批量导出的图片请使用“批量处理”结果窗口中的出图操作。</p>
<p>其他方式：右上角“分享”可预览后发送到已配置的 WebDAV / 企业微信；“文件 → 打印预览”用于查看 A4 纸张布局。</p>
<p><a href="help:labels">先整理结果文字</a> · <a href="help:overlay">如何生成叠图</a></p>'''),
    Topic('overlay', '叠图与统一化', '自动配置 手动配置 叠加 曲线 比较 m 质量 0.50', '''
<ol><li>先打开需要比较的多个文件。</li>
<li>在“曲线图”菜单或图中右键的“叠加”子菜单，选择“新建叠图 · 手动配置…”或“新建叠图 · 自动配置…”。</li>
<li>从空白清单自行选择曲线；手动添加曲线时默认选择变化量信号，也可改成其他信号。检查坐标轴与单位兼容性。</li>
<li>确认后生成独立叠图。重复选择同一组曲线，也可再次生成新的叠图窗口。</li>
<li>点击该叠图使其成为活动图，再导出图片或点击右上角“分享”。</li></ol>
<p><b>统一化：</b>叠图右上角“统一化”会读取可匹配的 m，并要求逐条核对／填写质量，再换算到 0.50 mg。原质量小于 0.50 mg 时高度相应放大，大于 0.50 mg 时高度相应缩小。确认每条质量及单位后再比较。</p>
<p><a href="help:export">叠图导出步骤</a></p>'''),
    Topic('more', '批量、坐标与常用设置', 'Excel xlsx excal 批次 T1 T2 M H 缓存 默认文件夹 字体 大 超大 面积 积分', '''
<h3>批量提取 T1、T2、M、H</h3>
<ol><li>点击工具栏“批量处理”，选择多个数据文件。</li><li>等待本批次计算完成，在表格核对结果。</li><li>使用底部按钮出图、导出 XLSX，或复制后粘贴到 Excel。通过窗口的小按钮可查看本次／全部批次并筛选。</li></ol>
<p>批次记录只在本次应用运行期间保留；需要长期保存时请导出表格。</p>
<h3>修改坐标范围</h3>
<p>右键坐标轴数字或标题，或使用“重定刻度 → 手动”，填写起点、止点、标值间隔、刻度间隔及偏移后确定。</p>
<h3>设置与面积计算</h3>
<ul><li>“设置 → 数据路径…”：配置称量表 m、默认打开文件夹、粒径文件夹、m 缓存时长和界面大小。大／超大在重启后生效。</li>
<li>“分析 → 区间面积计算与公式…”：选择积分坐标与基线，查看正、负、净及绝对面积，支持复制与 XLSX。时间积分和温度积分的单位不同。</li></ul>
<p><a href="help:right_click">返回右键操作</a> · <a href="help:start">从第一步开始</a></p>'''),
)
BY_KEY = {topic.key: topic for topic in TOPICS}


class HelpTopicsDialog(QDialog):
    def __init__(self, owner, topic='start', parent=None):
        super().__init__(parent if parent is not None else owner)
        self.setObjectName('HelpTopicsDialog')
        self.setWindowTitle(f'操作教学 · {APP_NAME}')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(False)
        self.resize(1000, 720)
        self.setMinimumSize(720, 480)
        layout = QVBoxLayout(self)
        heading = QLabel('操作教学与帮助主题')
        heading.setStyleSheet('font-size:18px; font-weight:bold; color:#765d86;')
        layout.addWidget(heading)
        hint = QLabel('无需联网；可把本窗口放在图旁边阅读。阅读教程不会修改数据或开始分析。')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setObjectName('HelpSearch')
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText('搜索：右键、T1、T2、H、文件信息、导出图片…')
        layout.addWidget(self.search)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.topics = QListWidget(); self.topics.setObjectName('HelpTopicList')
        self.topics.setMinimumWidth(185)
        self.browser = QTextBrowser(); self.browser.setObjectName('HelpArticle')
        self.browser.setOpenLinks(False); self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultFont(self.font())
        self.browser.document().setDefaultStyleSheet('''
            body { color:#453c56; } h1 { color:#765d86; font-size:20pt; }
            h3 { color:#795982; margin-top:18px; } p,li { line-height:140%; }
            li { margin-bottom:10px; } a { color:#6c609e; } th { text-align:left; }
        ''')
        split.addWidget(self.topics); split.addWidget(self.browser)
        split.setStretchFactor(1, 1); split.setSizes([245, 725]); layout.addWidget(split, 1)
        row = QHBoxLayout(); self.count = QLabel(); row.addWidget(self.count, 1)
        self.home = QPushButton('从头开始'); self.home.setToolTip('清空搜索并返回快速上手教程。')
        self.previous = QPushButton('上一主题'); self.next = QPushButton('下一主题')
        self.close_button = QPushButton('关闭'); self.close_button.setAutoDefault(False)
        for button in (self.home, self.previous, self.next, self.close_button):
            button.setAutoDefault(False); row.addWidget(button)
        layout.addLayout(row)
        self.search.textChanged.connect(self.filter_topics)
        self.topics.currentRowChanged.connect(self.render_current)
        self.browser.anchorClicked.connect(self.follow_link)
        self.home.clicked.connect(lambda: self.open_topic('start'))
        self.previous.clicked.connect(lambda: self.topics.setCurrentRow(self.topics.currentRow()-1))
        self.next.clicked.connect(lambda: self.topics.setCurrentRow(self.topics.currentRow()+1))
        self.close_button.clicked.connect(self.close)
        self.filter_topics(''); self.open_topic(topic)

    def filter_topics(self, query):
        old = self.current_key()
        self.topics.blockSignals(True); self.topics.clear()
        for topic in TOPICS:
            if topic.matches(query):
                item = QListWidgetItem(topic.title)
                item.setData(Qt.ItemDataRole.UserRole, topic.key)
                self.topics.addItem(item)
        index = next((i for i in range(self.topics.count())
                      if self.topics.item(i).data(Qt.ItemDataRole.UserRole)==old), 0)
        self.topics.setCurrentRow(index if self.topics.count() else -1)
        self.topics.blockSignals(False); self.render_current()

    def current_key(self):
        item = self.topics.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def render_current(self, *_):
        topic = BY_KEY.get(self.current_key())
        self.browser.setHtml(f'<h1>{topic.title}</h1>{topic.body}' if topic else
                             '<h1>未找到主题</h1><p>请尝试“右键”“变化”“文件信息”或“导出图片”，也可清空搜索。</p>')
        self.browser.verticalScrollBar().setValue(0)
        row, count = self.topics.currentRow(), self.topics.count()
        self.count.setText(f'{row+1 if row>=0 else 0} / {count} 个主题')
        self.previous.setEnabled(row>0); self.next.setEnabled(0<=row<count-1)

    def open_topic(self, key):
        key = key if key in BY_KEY else 'start'
        self.search.clear()
        self.topics.setCurrentRow(next(i for i in range(self.topics.count())
                                      if self.topics.item(i).data(Qt.ItemDataRole.UserRole)==key))

    def follow_link(self, url):
        # The guide only navigates local topic IDs. Never launch external URLs,
        # read local files or execute application commands from article links.
        if url.scheme()=='help' and url.path() in BY_KEY:
            self.open_topic(url.path())


def show(owner, topic='start', parent=None):
    parent = parent if parent is not None else owner
    dialog = owner.dialogs.get('help_topics')
    if dialog is None:
        dialog = HelpTopicsDialog(owner, topic, parent)
        owner.dialogs['help_topics'] = dialog
    else:
        if dialog.parentWidget() is not parent:
            dialog.setParent(parent, Qt.WindowType.Dialog)
        dialog.open_topic(topic)
    dialog.show(); dialog.raise_(); dialog.activateWindow()
    return dialog
