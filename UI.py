# -*- coding: utf-8 -*-
"""
农作物害虫智能检测识别与大模型防控决策系统 - UI界面
由 Qt Designer 生成，手工转换为 Python 代码
"""

from PyQt5 import QtCore, QtGui, QtWidgets


# 整窗样式表：按钮的悬停/按下/禁用态、表格、输入框统一在这里定义。
# 按钮不再各自内联 background-color（内联样式会盖掉 :hover/:pressed/:disabled，
# 原来点下去、禁用时外观完全没变化）；特殊按钮用 property "variant" 区分。
# ⚠️ main.py 的 init_UI_config 会在此基础上追加背景图规则，不要直接覆盖。
APP_STYLE = """
* { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif; }
QWidget#centralwidget { background-color: #e7eee4; }
QLabel#label_title { color: #1d3a24; letter-spacing: 1px; }
QPushButton {
    background-color: #2f6b3c; color: #ffffff; border: none; border-radius: 9px;
    padding: 0 8px; font-weight: 600;
}
QPushButton:hover { background-color: #3b7f4a; }
QPushButton:pressed { background-color: #22532d; padding-top: 2px; }
QPushButton:disabled { background-color: #a7b6a9; color: #f1f4f1; }
QPushButton[variant="primary"] { background-color: #1f6b35; border-radius: 12px; }
QPushButton[variant="primary"]:hover { background-color: #278143; }
QPushButton[variant="muted"] { background-color: #5b6a5e; }
QPushButton[variant="muted"]:hover { background-color: #6b7b6e; }
QPushButton[variant="ok"] { background-color: #1e8a4b; }
QPushButton[variant="ok"]:hover { background-color: #25a058; }
QPushButton[variant="danger"] { background-color: #b0392f; }
QPushButton[variant="danger"]:hover { background-color: #c5463b; }
QLineEdit, QTextEdit, QComboBox {
    background-color: #ffffff; color: #1d2a20; border: 1px solid #c9d6c6; border-radius: 8px;
    padding: 3px 8px; selection-background-color: #2f6b3c; selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #2f6b3c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #d6eadb; selection-color: #1d2a20; }
QTableWidget {
    background-color: #ffffff; alternate-background-color: #f3f7f2; color: #1d2a20;
    gridline-color: #e1e9df; border: 1px solid #cfdacc; border-radius: 10px;
    selection-background-color: #cfe6d4; selection-color: #12301b;
}
QHeaderView::section {
    background-color: #2f5a37; color: #ffffff; border: none; border-right: 1px solid #3d6b46;
    padding: 6px 4px; font-weight: 600;
}
QTableCornerButton::section { background-color: #2f5a37; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #b9c8b7; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #8fa68c; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background-color: #1d2a20; color: #ffffff; border: none; padding: 4px 8px; }
"""


# 底部表格列宽：编号/图片/输入时间/识别结果/目标数量/耗时/评判/保存状态（最后一列自动拉伸）
TABLE_COLUMN_WIDTHS = [50, 150, 150, 250, 70, 70, 90, 80]


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1280, 820)
        MainWindow.setMinimumSize(1024, 700)

        # 中央控件
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        # ==================== 顶部标题 ====================
        self.label_title = QtWidgets.QLabel(self.centralwidget)
        self.label_title.setGeometry(QtCore.QRect(10, 5, 1260, 36))
        font_title = QtGui.QFont()
        font_title.setFamily("Arial")
        font_title.setPointSize(16)
        font_title.setBold(True)
        self.label_title.setFont(font_title)
        self.label_title.setAlignment(QtCore.Qt.AlignCenter)
        self.label_title.setObjectName("label_title")

        # ==================== 左侧控制面板区域 ====================
        self.label_control = QtWidgets.QLabel(self.centralwidget)
        self.label_control.setGeometry(QtCore.QRect(10, 50, 280, 760))
        self.label_control.setObjectName("label_control")

        # ---- 源选择按钮区域 ----
        # 打开图片按钮
        self.pushButton_img = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_img.setGeometry(QtCore.QRect(30, 70, 110, 36))
        font_btn = QtGui.QFont()
        font_btn.setFamily("Arial")
        font_btn.setPointSize(10)
        self.pushButton_img.setFont(font_btn)
        self.pushButton_img.setText("打开图片")
        self.pushButton_img.setObjectName("pushButton_img")

        # 打开文件夹按钮
        self.pushButton_dir = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_dir.setGeometry(QtCore.QRect(160, 70, 110, 36))
        self.pushButton_dir.setFont(font_btn)
        self.pushButton_dir.setText("打开文件夹")
        self.pushButton_dir.setObjectName("pushButton_dir")

        # 打开视频按钮
        self.pushButton_video = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_video.setGeometry(QtCore.QRect(30, 120, 110, 36))
        self.pushButton_video.setFont(font_btn)
        self.pushButton_video.setText("打开视频")
        self.pushButton_video.setObjectName("pushButton_video")

        # 打开摄像头按钮
        self.pushButton_camera = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_camera.setGeometry(QtCore.QRect(160, 120, 110, 36))
        self.pushButton_camera.setFont(font_btn)
        self.pushButton_camera.setText("打开摄像头")
        self.pushButton_camera.setObjectName("pushButton_camera")

        # 开始运行按钮
        self.pushButton_start = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_start.setGeometry(QtCore.QRect(30, 180, 240, 40))
        font_start = QtGui.QFont()
        font_start.setFamily("Arial")
        font_start.setPointSize(12)
        font_start.setBold(True)
        self.pushButton_start.setFont(font_start)
        self.pushButton_start.setText("开始运行 >")
        self.pushButton_start.setProperty("variant", "primary")
        self.pushButton_start.setObjectName("pushButton_start")

        # ---- 拍照识别 / 关闭摄像头（手持人工确认场景：拍一张 → 立刻识别）----
        self.pushButton_snap = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_snap.setGeometry(QtCore.QRect(30, 232, 115, 34))
        self.pushButton_snap.setFont(font_start)
        self.pushButton_snap.setText("📷 拍照识别")
        self.pushButton_snap.setObjectName("pushButton_snap")

        self.pushButton_cam_close = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_cam_close.setGeometry(QtCore.QRect(155, 232, 115, 34))
        self.pushButton_cam_close.setFont(font_start)
        self.pushButton_cam_close.setText("⏹ 关闭摄像头")
        self.pushButton_cam_close.setProperty("variant", "muted")
        self.pushButton_cam_close.setObjectName("pushButton_cam_close")

        # ---- 路径显示区域 ----
        # ⚠️ 这几行必须排在「📷 拍照识别 / ⏹ 关闭摄像头」按钮（y 232..266）**下方**。
        #    原来 label_img_path 从 y=240 起，正好压住按钮下半部分：QLabel 创建更晚
        #    → z 序更高 → 点击被它吃掉，而 Qt 不会把被忽略的点击传给下层兄弟控件，
        #    表现就是"点拍照识别完全没反应、也没有任何日志"（现场真实故障）。
        font_path = QtGui.QFont()
        font_path.setFamily("Arial")
        font_path.setPointSize(8)

        self.label_img_path = QtWidgets.QLabel(self.centralwidget)
        self.label_img_path.setGeometry(QtCore.QRect(30, 270, 240, 20))
        self.label_img_path.setFont(font_path)
        self.label_img_path.setText(" 选择图片文件")
        self.label_img_path.setStyleSheet("color: rgb(60,60,60);")
        self.label_img_path.setObjectName("label_img_path")

        self.label_dir_path = QtWidgets.QLabel(self.centralwidget)
        self.label_dir_path.setGeometry(QtCore.QRect(30, 290, 240, 20))
        self.label_dir_path.setFont(font_path)
        self.label_dir_path.setText(" 选择图片文件夹")
        self.label_dir_path.setStyleSheet("color: rgb(60,60,60);")
        self.label_dir_path.setObjectName("label_dir_path")

        self.label_video_path = QtWidgets.QLabel(self.centralwidget)
        self.label_video_path.setGeometry(QtCore.QRect(30, 310, 240, 20))
        self.label_video_path.setFont(font_path)
        self.label_video_path.setText(" 选择视频文件")
        self.label_video_path.setStyleSheet("color: rgb(60,60,60);")
        self.label_video_path.setObjectName("label_video_path")

        self.label_camera_path = QtWidgets.QLabel(self.centralwidget)
        self.label_camera_path.setGeometry(QtCore.QRect(30, 330, 240, 20))
        self.label_camera_path.setFont(font_path)
        self.label_camera_path.setText(" 打开摄像头")
        self.label_camera_path.setStyleSheet("color: rgb(60,60,60);")
        self.label_camera_path.setObjectName("label_camera_path")

        # ---- 目标选择器 ----
        self.comboBox = QtWidgets.QComboBox(self.centralwidget)
        self.comboBox.setGeometry(QtCore.QRect(30, 350, 240, 28))
        font_combo = QtGui.QFont()
        font_combo.setFamily("Arial")
        font_combo.setPointSize(10)
        self.comboBox.setFont(font_combo)
        self.comboBox.setObjectName("comboBox")
        self.comboBox.addItems(["所有目标"])

        # ---- 检测信息显示 ----
        font_info = QtGui.QFont()
        font_info.setFamily("Arial")
        font_info.setPointSize(9)

        y_info = 400

        # 类别
        label_cls_title = QtWidgets.QLabel(self.centralwidget)
        label_cls_title.setGeometry(QtCore.QRect(30, y_info, 60, 24))
        label_cls_title.setFont(font_info)
        label_cls_title.setText("类别:")
        label_cls_title.setStyleSheet("font-weight: bold;")

        self.label_class = QtWidgets.QLabel(self.centralwidget)
        self.label_class.setGeometry(QtCore.QRect(90, y_info, 170, 24))
        self.label_class.setFont(font_info)
        self.label_class.setText("--")
        self.label_class.setObjectName("label_class")

        y_info += 30
        # 置信度
        label_score_title = QtWidgets.QLabel(self.centralwidget)
        label_score_title.setGeometry(QtCore.QRect(30, y_info, 60, 24))
        label_score_title.setFont(font_info)
        label_score_title.setText("置信度:")
        label_score_title.setStyleSheet("font-weight: bold;")

        self.label_score = QtWidgets.QLabel(self.centralwidget)
        self.label_score.setGeometry(QtCore.QRect(90, y_info, 170, 24))
        self.label_score.setFont(font_info)
        self.label_score.setText("--")
        self.label_score.setObjectName("label_score")

        y_info += 30
        # 风险等级
        label_risk_title = QtWidgets.QLabel(self.centralwidget)
        label_risk_title.setGeometry(QtCore.QRect(30, y_info, 60, 24))
        label_risk_title.setFont(font_info)
        label_risk_title.setText("风险等级:")
        label_risk_title.setStyleSheet("font-weight: bold;")

        self.label_risk = QtWidgets.QLabel(self.centralwidget)
        self.label_risk.setGeometry(QtCore.QRect(90, y_info, 170, 24))
        font_risk = QtGui.QFont()
        font_risk.setFamily("Arial")
        font_risk.setPointSize(11)
        font_risk.setBold(True)
        self.label_risk.setFont(font_risk)
        self.label_risk.setText("--")
        self.label_risk.setObjectName("label_risk")

        y_info += 30
        # 边界框坐标
        label_coords_title = QtWidgets.QLabel(self.centralwidget)
        label_coords_title.setGeometry(QtCore.QRect(30, y_info, 60, 24))
        label_coords_title.setFont(font_info)
        label_coords_title.setText("坐标:")
        label_coords_title.setStyleSheet("font-weight: bold;")

        y_info += 25
        self.label_xmin_v = QtWidgets.QLabel(self.centralwidget)
        self.label_xmin_v.setGeometry(QtCore.QRect(30, y_info, 100, 20))
        self.label_xmin_v.setFont(font_info)
        self.label_xmin_v.setText("xmin: --")
        self.label_xmin_v.setObjectName("label_xmin_v")

        self.label_ymin_v = QtWidgets.QLabel(self.centralwidget)
        self.label_ymin_v.setGeometry(QtCore.QRect(140, y_info, 100, 20))
        self.label_ymin_v.setFont(font_info)
        self.label_ymin_v.setText("ymin: --")
        self.label_ymin_v.setObjectName("label_ymin_v")

        y_info += 22
        self.label_xmax_v = QtWidgets.QLabel(self.centralwidget)
        self.label_xmax_v.setGeometry(QtCore.QRect(30, y_info, 100, 20))
        self.label_xmax_v.setFont(font_info)
        self.label_xmax_v.setText("xmax: --")
        self.label_xmax_v.setObjectName("label_xmax_v")

        self.label_ymax_v = QtWidgets.QLabel(self.centralwidget)
        self.label_ymax_v.setGeometry(QtCore.QRect(140, y_info, 100, 20))
        self.label_ymax_v.setFont(font_info)
        self.label_ymax_v.setText("ymax: --")
        self.label_ymax_v.setObjectName("label_ymax_v")

        # ---- 操作按钮 ----
        y_btn = y_info + 40

        self.pushButton_save = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_save.setGeometry(QtCore.QRect(30, y_btn, 110, 36))
        self.pushButton_save.setFont(font_btn)
        self.pushButton_save.setText("保存结果")
        self.pushButton_save.setObjectName("pushButton_save")

        self.pushButton_export = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_export.setGeometry(QtCore.QRect(160, y_btn, 110, 36))
        self.pushButton_export.setFont(font_btn)
        self.pushButton_export.setText("导出数据")
        self.pushButton_export.setObjectName("pushButton_export")

        y_btn += 50
        self.pushButton_advice = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_advice.setGeometry(QtCore.QRect(30, y_btn, 240, 36))
        self.pushButton_advice.setFont(font_btn)
        self.pushButton_advice.setText("获取防治建议(AI)")
        self.pushButton_advice.setObjectName("pushButton_advice")

        # ---- AI建议文本框 ----
        y_text = y_btn + 50
        self.textEdit_advice = QtWidgets.QTextEdit(self.centralwidget)
        self.textEdit_advice.setGeometry(QtCore.QRect(30, y_text, 240, 100))
        font_advice = QtGui.QFont()
        font_advice.setFamily("Arial")
        font_advice.setPointSize(8)
        self.textEdit_advice.setFont(font_advice)
        self.textEdit_advice.setReadOnly(True)
        self.textEdit_advice.setPlaceholderText("AI防治建议将显示在这里...")
        self.textEdit_advice.setObjectName("textEdit_advice")

        # ---- 大模型自由问答（RAG + 防幻觉）输入区 ----
        # 与"获取防治建议"共用同一个显示框：建议在上、问答在下，不额外占布局
        y_chat = y_text + 100
        self.lineEdit_chat = QtWidgets.QLineEdit(self.centralwidget)
        self.lineEdit_chat.setGeometry(QtCore.QRect(30, y_chat, 176, 30))
        font_chat = QtGui.QFont()
        font_chat.setFamily("Arial")
        font_chat.setPointSize(9)
        self.lineEdit_chat.setFont(font_chat)
        self.lineEdit_chat.setPlaceholderText("向本地大模型提问…")
        self.lineEdit_chat.setObjectName("lineEdit_chat")

        self.pushButton_chat = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_chat.setGeometry(QtCore.QRect(212, y_chat, 58, 30))
        font_chat_btn = QtGui.QFont()
        font_chat_btn.setFamily("Arial")
        font_chat_btn.setPointSize(9)
        self.pushButton_chat.setFont(font_chat_btn)
        self.pushButton_chat.setText("提问")
        self.pushButton_chat.setObjectName("pushButton_chat")

        # ==================== 右侧主图显示区域 ====================
        self.label_img = QtWidgets.QLabel(self.centralwidget)
        self.label_img.setGeometry(QtCore.QRect(300, 50, 660, 460))
        self.label_img.setAlignment(QtCore.Qt.AlignCenter)
        self.label_img.setScaledContents(False)
        self.label_img.setObjectName("label_img")

        # ==================== 右侧现场评测面板 ====================
        # 位置：图像区右侧的空白带（x=970..1260 / y=50..510），不与底部表格（y>=520）重叠。
        # 评委现场要看的就是这里的倒计时与三项得分。
        font_eval_title = QtGui.QFont()
        font_eval_title.setFamily("Arial")
        font_eval_title.setPointSize(12)
        font_eval_title.setBold(True)

        self.label_eval_title = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_title.setGeometry(QtCore.QRect(970, 50, 290, 28))
        self.label_eval_title.setFont(font_eval_title)
        self.label_eval_title.setText("现场评测")
        self.label_eval_title.setStyleSheet("font-weight: bold;")
        self.label_eval_title.setObjectName("label_eval_title")

        # 大字倒计时（<=180s 倒着走；超时后显示 +Ns 并转红）
        font_eval_timer = QtGui.QFont()
        font_eval_timer.setFamily("Arial")
        font_eval_timer.setPointSize(30)
        font_eval_timer.setBold(True)

        self.label_eval_timer = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_timer.setGeometry(QtCore.QRect(970, 80, 290, 62))
        self.label_eval_timer.setFont(font_eval_timer)
        self.label_eval_timer.setAlignment(QtCore.Qt.AlignCenter)
        self.label_eval_timer.setText("03:00")
        self.label_eval_timer.setObjectName("label_eval_timer")

        font_eval_info = QtGui.QFont()
        font_eval_info.setFamily("Arial")
        font_eval_info.setPointSize(9)

        self.label_eval_progress = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_progress.setGeometry(QtCore.QRect(970, 146, 290, 22))
        self.label_eval_progress.setFont(font_eval_info)
        self.label_eval_progress.setText("样本 0 / 20    已评判 0")
        self.label_eval_progress.setObjectName("label_eval_progress")

        self.label_eval_acc = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_acc.setGeometry(QtCore.QRect(970, 176, 290, 24))
        self.label_eval_acc.setFont(font_eval_info)
        self.label_eval_acc.setText("准确度    0.0 / 20")
        self.label_eval_acc.setObjectName("label_eval_acc")

        self.label_eval_time = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_time.setGeometry(QtCore.QRect(970, 202, 290, 24))
        self.label_eval_time.setFont(font_eval_info)
        self.label_eval_time.setText("时效性   --  / 10")
        self.label_eval_time.setObjectName("label_eval_time")

        font_eval_total = QtGui.QFont()
        font_eval_total.setFamily("Arial")
        font_eval_total.setPointSize(14)
        font_eval_total.setBold(True)

        self.label_eval_total = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_total.setGeometry(QtCore.QRect(970, 232, 290, 34))
        self.label_eval_total.setFont(font_eval_total)
        self.label_eval_total.setText("总分    0.0 / 30")
        self.label_eval_total.setObjectName("label_eval_total")

        font_eval_hint = QtGui.QFont()
        font_eval_hint.setFamily("Arial")
        font_eval_hint.setPointSize(8)

        self.label_eval_hint = QtWidgets.QLabel(self.centralwidget)
        self.label_eval_hint.setGeometry(QtCore.QRect(970, 272, 290, 40))
        self.label_eval_hint.setFont(font_eval_hint)
        self.label_eval_hint.setWordWrap(True)
        self.label_eval_hint.setText("点表格行回看照片 → 点下面 ✔/✘ 评判。\n"
                                     "倒计时从第一张样本自动开始。")
        self.label_eval_hint.setStyleSheet("color: rgb(90,90,90);")
        self.label_eval_hint.setObjectName("label_eval_hint")

        # 开始新一轮 / 结束本轮（文案与行为随会话状态切换）
        self.pushButton_eval_start = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_eval_start.setGeometry(QtCore.QRect(970, 316, 290, 34))
        self.pushButton_eval_start.setFont(font_btn)
        self.pushButton_eval_start.setText("↻ 新一轮评测（清空日志）")
        self.pushButton_eval_start.setObjectName("pushButton_eval_start")

        # 评委判分：作用于当前回看的那一行
        self.pushButton_verdict_ok = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_verdict_ok.setGeometry(QtCore.QRect(970, 356, 140, 40))
        self.pushButton_verdict_ok.setFont(font_start)
        self.pushButton_verdict_ok.setText("✔ 识别正确")
        self.pushButton_verdict_ok.setProperty("variant", "ok")
        self.pushButton_verdict_ok.setObjectName("pushButton_verdict_ok")

        self.pushButton_verdict_bad = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_verdict_bad.setGeometry(QtCore.QRect(1120, 356, 140, 40))
        self.pushButton_verdict_bad.setFont(font_start)
        self.pushButton_verdict_bad.setText("✘ 识别错误")
        self.pushButton_verdict_bad.setProperty("variant", "danger")
        self.pushButton_verdict_bad.setObjectName("pushButton_verdict_bad")

        self.pushButton_eval_export = QtWidgets.QPushButton(self.centralwidget)
        self.pushButton_eval_export.setGeometry(QtCore.QRect(970, 404, 290, 32))
        self.pushButton_eval_export.setFont(font_btn)
        self.pushButton_eval_export.setText("导出评分报告")
        self.pushButton_eval_export.setObjectName("pushButton_eval_export")

        # ==================== 底部结果表格 ====================
        # ⚠️ 这张表只记"样本"（拍照识别 / 打开图片 / 打开文件夹），实时检测不写。
        self.tableWidget_info = QtWidgets.QTableWidget(self.centralwidget)
        self.tableWidget_info.setGeometry(QtCore.QRect(300, 520, 960, 290))
        self.tableWidget_info.setColumnCount(8)
        self.tableWidget_info.setHorizontalHeaderLabels([
            "编号", "图片", "输入时间", "识别结果", "目标数量", "耗时", "评判", "保存状态"
        ])
        # 设置列宽（合计 ≈ 940 ≤ 960；最后一列自动拉伸）
        for i, w in enumerate(TABLE_COLUMN_WIDTHS):
            self.tableWidget_info.setColumnWidth(i, w)
        self.tableWidget_info.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tableWidget_info.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tableWidget_info.setAlternatingRowColors(True)
        # 第 0 列就是"编号"，行号表头重复且挤占宽度；最后一列拉伸填满，避免右侧被截断
        self.tableWidget_info.verticalHeader().setVisible(False)
        self.tableWidget_info.verticalHeader().setDefaultSectionSize(34)
        self.tableWidget_info.horizontalHeader().setStretchLastSection(True)
        self.tableWidget_info.setWordWrap(False)
        self.tableWidget_info.setObjectName("tableWidget_info")

        MainWindow.setCentralWidget(self.centralwidget)
        MainWindow.setStyleSheet(APP_STYLE)

        QtCore.QMetaObject.connectSlotsByName(MainWindow)
