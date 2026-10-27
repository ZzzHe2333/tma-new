"""Concrete hover help for toolbar commands and shared dialog buttons."""
ACTION_HELP = {
    'HelpTopics1':'打开可搜索的离线操作教学：右键选点、尺寸／信号变化、独立标签、文件信息与图片导出。也可按 F1。',
    'GettingStartedGuide1':'打开从导入数据、右键测量到导出图片的逐步入门教学。',
    'HowTo1':'查看右键操作教学：空白处分析菜单、选点时确定／编辑／取消、文字与坐标轴的右键区别。',
    'FileInformation1':'查看或编辑当前文件的样品、操作者、方法、备注和支持的尺寸；点击窗口“帮助”查看步骤与保存说明。',
    'Open1':'导入一个或多个 TA 数据文件（.001、.002 等）。每次打开独立成图，也可用于批量处理和叠图比较。',
    'Print1':'打印当前活动图像或叠图，包括坐标轴和标注；默认 A4，横图横向、竖图纵向，等比例居中。',
    'PrintSetup1':'设置打印纸张、横向或纵向及四侧页边距。默认 A4、方向随图；保存后供打印和预览使用，重启保留。',
    'PrintPreview1':'预览当前活动图在纸张上的完整布局；默认 A4、方向随图，可在预览中调整方向并打印。',
    'ExportPlot1':'导出当前活动图像（含叠图）：支持 PNG、SVG、PDF、TIFF，保留曲线、标注和外围白边。',
    'ExportPDFFile1':'把当前活动图像或叠图导出为 PDF。',
    'Annotate1':'给当前图添加多行批注，可填写方法日志和称取质量，并调整批注的位置与外观。',
    'ManualRescale1':'手动设置 X、Y1–Y4 的起止值、标值间隔、刻度间隔和标值偏移。也可右键坐标轴进入。',
    'FullScaleAll1':'对当前图的全部坐标轴自动重定刻度，使可见曲线落入显示范围。',
    'CommonScale1':'通用刻度：此入口暂未接入，当前请使用手动重定刻度或全部坐标轴满刻度。',
    'ParamsSameAs1':'参数同于：此入口暂未接入，可通过各曲线图选项分别设置。',
    'Signals1':'选择当前文件在 Y1–Y4 显示哪些采集信号，配置数据类型和单位。',
    'FullRangeLimits1':'恢复当前文件的完整数据范围，取消此前设置的时间或温度数据界限。',
    'TimeLimits1':'按采集时间设置数据范围，用于限制当前图和分析使用的数据区间。',
    'TemperatureLimits1':'按温度设置数据范围，用于限制当前图和分析使用的数据区间。',
    'Curve1':'选择曲线并修改信号或曲线参数。',
    'AutoConfigure1':'新建叠图 · 自动配置\n从空白清单手动勾选要比较的曲线，再选择 Y 轴、自动颜色、线型、符号、图例和偏移。确定后生成独立叠图，可导出图片或分享。',
    'ManualSetup1':'新建叠图 · 手动配置\n初始不加入任何曲线。点击“添加曲线”自行选择文件，信号默认选择尺寸变化（变化量），可手动修改；再逐条调整颜色、线型、符号、偏移及坐标轴。确定后可导出或分享叠图。',
    'Edit4':'编辑当前叠图：保留已有曲线，添加、删除、排序、换轴，并修改外观、标题、图例和网格。',
    'GraphOptions1':'修改当前图的坐标轴、网格、符号等显示选项；当前为叠图时打开叠图编辑窗口。',
    'AlphaAtX1':'计算所选温度附近的热膨胀系数 Alpha；需要样品原始尺寸，可在曲线上调整分析点。',
    'AlphaX1ToX21':'选择两个温度，以两点间尺寸变化计算区间热膨胀系数 Alpha。',
    'AlphaFitX1ToX21':'选择温度区间，对区间曲线做线性拟合并计算 Alpha。',
    'DimensionChange1':'尺寸变化：拖动两个曲线点或手动输入温度，计算 T1、T2 和高度差 H；各文字标注可独立调整。右键确定、编辑或取消。',
    'HeightChange':'高度差：选择两个曲线点，计算两点的高度差并生成可编辑标注。',
    'Linear1':'线性峰积分：选择峰区间，按线性基线计算面积，并在图上显示分析结果。',
    'RunningIntegral1':'独立区间面积：无需先做峰积分；选择实际时间或当前X积分，支持四种基线，查看正、负、净及绝对面积与公式，可复制和导出XLSX。',
    'SigHorizontal1':'水平 S 形基线积分：选择峰区间，迭代拟合 S 形基线并计算峰面积。',
    'PeakMax1':'在所选峰区间寻找峰最大位置，可调整界限和分析点。',
    'SignalMax1':'信号最大：初始定位曲线最大值，可左右拖到其他坐标；确定后显示温度标注。',
    'SignalChange1':'信号变化：选择两个曲线点，计算信号差及对应坐标。右键可确定、输入温度或取消。',
    'GlassTransition1':'玻璃化转变：调整分析区间并拟合转变前后基线，标注玻璃化温度。',
    'OnsetPoint1':'始点分析：通过基线和切线求交点，计算转变开始位置。',
    'Slope1':'斜率：在曲线上选择分析区间，计算尺寸变化随 X 轴的变化率。',
    'CurveValueAtX1':'按指定 X 坐标读取曲线值，可在图上拖动点或手动输入具体坐标。',
    'AnalysisOptions1':'设置分析算法和标注选项，供后续分析使用。',
    'Smooth1':'对当前曲线进行平滑，调整平滑方法和窗口宽度；保留原始采集数据。',
    'Shift1':'调整当前曲线的平移和相关曲线参数，便于定位或比较。',
    'ShowOverlayPlot1':'按当前曲线状态打开叠图；需要从空白挑选曲线时，请使用新建叠图的手动或自动配置。',
    'ShowNormalPlot1':'返回当前文件的普通曲线图，保留已有叠图窗口。',
    'Copy3':'复制当前活动图像到剪贴板，可粘贴到文档或聊天窗口。',
    'Copy4':'复制一张已有叠图作为独立窗口，之后可分别调整成员曲线、外观和坐标。',
    'SaveSession1':'按需保存当前分析文件，保留图形设置和分析结果，供之后恢复。',
    'PathSettings1':'配置称重表 m、默认导入文件夹、粒径文件夹、缓存频率和界面大小。',
    'BatchAnalysis1':'批量导入 TMA 文件，提取 T1、T2、M、H，并导出图片、XLSX 或复制表格。',
    'SingleReport1':'选取 TMA 与粒径文件，核对数据后生成单样品 PDF 报告；支持可选模板。',
}

BUTTON_HELP = {
    '确定':'应用当前窗口的选择和参数。校验成功后关闭窗口；新建叠图时生成所选曲线的叠图。',
    '取消':'关闭窗口，放弃本次尚未确认的选择和设置。',
    '关闭':'关闭当前窗口，返回数据处理界面。',
    '保存':'保存当前窗口的设置；分析文件、图像和表格请使用对应的保存或导出入口。',
    '默认值':'恢复当前设置页的默认参数，确认后应用。',
    '帮助':'显示当前功能的操作说明和参数用途。',
    '添加曲线':'自行勾选文件，默认使用尺寸变化（变化量）信号，也可改选其他信号；加入当前叠图草稿，每个 Y 轴最多十条兼容曲线。',
    '删除曲线':'从当前叠图草稿移除选中的曲线，不删除源数据文件。',
    '全部删除':'清空当前坐标轴上的叠图成员，再通过添加曲线重新选择。',
    '自动线条':'按叠图“自动”页的线型序列，为当前坐标轴上的曲线分配线型。',
    '自动符号':'按叠图“自动”页的符号序列，为当前坐标轴上的曲线分配数据点符号。',
    '自动颜色':'按叠图“自动”页的颜色序列，为当前坐标轴上的曲线分配颜色。',
    '自动偏移':'按设置的偏移规则错开当前坐标轴上的曲线，便于比较。',
    '全部选择':'手动全选此窗口列出的候选文件或曲线。',
    '取消选择':'取消此窗口中所有候选文件或曲线的勾选。',
    '分享':'预览当前活动图或叠图，再发送到配置好的 WebDAV 或企业微信渠道。',
    '导出图像':'导出当前活动图或叠图，保留曲线、标注及外围白边。',
    '批量处理':'批量提取 T1、T2、M、H，可出图、导出 XLSX 或复制表格。',
    '单样品报告':'结合一个 TMA 文件与粒径记录，核对信息后生成 PDF 报告。',
    '登录':'保存本机使用的昵称；登录后可在“用户 → 我的会员”输入授权码。',
    '激活授权':'校验授权码并绑定当前机器码；激活后显示永久激活，昵称显示红色。',
    '购买会员':'显示销售联系提示。',
    '全范围':'把当前数据或分析界限恢复到完整可用范围。',
    '强制刷新 m':'跳过已有缓存重新读取称重数据；在后台匹配样品质量。',
}


def describe_action(name, caption):
    return ACTION_HELP.get(name, f'{caption}：打开对应功能，按窗口中的文件选择与参数提示进行操作。')


def install(application):
    if getattr(application, '_tma_help_filter', None) is not None: return
    from PySide6.QtCore import QObject, QEvent, Qt
    from PySide6.QtWidgets import QAbstractButton, QToolButton, QMenu
    class HelpFilter(QObject):
        def eventFilter(self, target, event):
            if event.type() == QEvent.Type.Show:
                if isinstance(target, QMenu): target.setToolTipsVisible(True)
                if isinstance(target, QAbstractButton) and not target.toolTip():
                    action = target.defaultAction() if isinstance(target, QToolButton) else None
                    text = target.text().replace('&', '').strip().rstrip('… .')
                    help_text = action.toolTip() if action is not None else ''
                    if not help_text:
                        help_text = BUTTON_HELP.get(text)
                        if help_text is None:
                            if text.startswith('Y') and text[1:].isdigit(): help_text = '选择此 Y 轴，查看或设置该轴上的信号与曲线。'
                            elif text.startswith(('选择', '打开文件')): help_text = '打开选择窗口，手动选择本项需要的文件或文件夹。'
                            elif text.startswith(('导出', '出图')): help_text = f'{text}：选择保存位置，输出当前选择的数据或图像。'
                            elif text.startswith('复制'): help_text = '把当前选择的内容复制到剪贴板，可粘贴到其他应用。'
                            elif text: help_text = f'{target.window().windowTitle()}：{text}。操作范围以当前窗口的选项为准。'
                    if help_text: target.setToolTip(help_text)
                    target.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
            return False
    application._tma_help_filter = HelpFilter(application)
    application.installEventFilter(application._tma_help_filter)
