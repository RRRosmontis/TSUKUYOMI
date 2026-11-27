import asyncio
import json
import logging
import sys
import threading
import io
import urllib.request
from PIL import Image, ImageDraw
import pystray
from winotify import Notification, audio
import websockets
import pythoncom

# PyQt5 相关导入
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, 
                             QRadioButton, QPushButton, QSlider, 
                             QVBoxLayout, QHBoxLayout, QGroupBox, QMessageBox, 
                             QFrame, QScrollArea, QSizePolicy, QDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QPropertyAnimation, QPoint, QRect, QTimer
from PyQt5.QtGui import QIntValidator, QFont, QResizeEvent, QMouseEvent, QColor, QPainter, QBrush, QPen, QFontMetrics, QIcon, QPixmap, QImage

# ==================== 版本号 ====================
VERSION = "0.6.2"

# ==================== 配置日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("danmaku_client")

# ==================== 全局变量 ====================
exit_event = threading.Event()          # 退出标志
active_websockets = []                  # 所有活跃的 WebSocket 连接对象
ws_lock = threading.Lock()              # 保护 active_websockets 的线程锁

# 图标URL（若无法访问，将自动降级为默认图标）
ICON_URL = "https://cdn.rrrosmontis.icu/tsukuyomi/TKYM-Singl.png"

# ==================== 获取应用图标（供任务栏和托盘共用） ====================
def create_default_icon():
    size = 64
    img = Image.new('RGB', (size, size), color='white')
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, size-8, size-8], fill='blue', outline='darkblue')
    return img

def get_icon_image():
    try:
        with urllib.request.urlopen(ICON_URL, timeout=5) as response:
            img_data = response.read()
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            logger.info("成功加载远程图标")
            return img
    except Exception as e:
        logger.warning(f"加载远程图标失败: {e}，使用默认图标")
        return create_default_icon()

def get_qicon():
    """将 PIL Image 转换为 QIcon"""
    img = get_icon_image()
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimage = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage)
    return QIcon(pixmap)

# ==================== PyQt5 配置对话框（改为 QDialog） ====================
class ConfigDialog(QDialog):
    """美观的配置对话框，用于输入房间号、选择节点、显示模式"""
    def __init__(self):
        super().__init__()
        self.room_id = None
        self.mode = None
        self.opacity = 0.85          # 默认透明度
        self.font_size = 10          # 默认字号（减小）
        self.aspect_ratio = "9:16"   # 默认宽高比改为 9:16
        self.display_mode = "window" # 默认悬浮窗模式 ("window" 或 "notification")
        self.init_ui()
    
    def init_ui(self):
        """初始化界面组件"""
        self.setWindowTitle(f"TSUKUYOMI DANMAKU - CONFIG")
        self.resize(500, 520)         # 稍微增加高度以容纳新模式选项
        self.setMinimumSize(400, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # 深色背景样式表（与原来一致）
        self.setStyleSheet("""
            QWidget {
                background-color: #0a0e17;
                color: #e0e0e0;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QLabel {
                color: #c0c0c0;
            }
            QLineEdit {
                background-color: #1e2434;
                border: 1px solid #2c3348;
                border-radius: 5px;
                padding: 8px 10px;
                color: #ffffff;
                font-size: 13px;
                selection-background-color: #3a425c;
            }
            QLineEdit:focus {
                border: 1px solid #5a6e8a;
            }
            QRadioButton {
                color: #d0d0d0;
                font-size: 13px;
                spacing: 10px;
                padding: 4px 0;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
            QRadioButton::indicator:unchecked {
                border: 1px solid #5a6e8a;
                border-radius: 8px;
                background-color: #1e2434;
            }
            QRadioButton::indicator:checked {
                border: 1px solid #7c9cbf;
                border-radius: 8px;
                background-color: #4c7a9a;
            }
            QPushButton {
                background-color: #2c3348;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a425c;
            }
            QPushButton:pressed {
                background-color: #1f2538;
            }
            QGroupBox {
                border: 1px solid #2c3348;
                border-radius: 8px;
                margin-top: 12px;
                font-size: 13px;
                font-weight: normal;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px 0 6px;
                color: #b0b0b0;
            }
        """)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(18)
        main_layout.setContentsMargins(25, 20, 25, 20)
        
        # 标题区域
        title_label = QLabel("TSUKUYOMI DANMAKU")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #d4d4d4; margin-bottom: 8px;")
        main_layout.addWidget(title_label)
        
        # 房间号输入区域
        room_layout = QVBoxLayout()
        room_label = QLabel("房间号 (1-100)")
        room_label.setStyleSheet("margin-bottom: 4px; font-weight: bold;")
        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("请输入数字房间号")
        self.room_edit.setValidator(QIntValidator(1, 100))
        room_layout.addWidget(room_label)
        room_layout.addWidget(self.room_edit)
        main_layout.addLayout(room_layout)
        
        # 节点选择区域
        node_group = QGroupBox("接入节点选择")
        node_group.setMinimumHeight(140)
        node_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        node_layout = QVBoxLayout()
        node_layout.setSpacing(10)
        node_layout.setContentsMargins(15, 12, 15, 12)
        
        self.radio_main = QRadioButton("[主站] api.rrrosmontis.icu")
        self.radio_backup = QRadioButton("[副站] tsk.aeolianchi.me")
        self.radio_both = QRadioButton("[主站+副站] 同时接收")
        
        self.radio_main.setChecked(True)
        
        node_layout.addWidget(self.radio_main)
        node_layout.addWidget(self.radio_backup)
        node_layout.addWidget(self.radio_both)
        node_layout.addStretch()
        node_group.setLayout(node_layout)
        main_layout.addWidget(node_group)
        
        # ========== 新增：显示模式选择（悬浮窗 / 通知） ==========
        mode_group = QGroupBox("显示模式")
        mode_layout = QVBoxLayout()
        mode_layout.setSpacing(10)
        mode_layout.setContentsMargins(15, 12, 15, 12)
        self.radio_window = QRadioButton("悬浮窗模式")
        self.radio_notification = QRadioButton("通知模式")
        self.radio_window.setChecked(True)  # 默认悬浮窗
        mode_layout.addWidget(self.radio_window)
        mode_layout.addWidget(self.radio_notification)
        mode_group.setLayout(mode_layout)
        main_layout.addWidget(mode_group)
        
        # 添加弹性空间
        main_layout.addStretch(1)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(25)
        self.start_btn = QPushButton("启动接收")
        self.start_btn.setMinimumHeight(36)
        self.cancel_btn = QPushButton("退出程序")
        self.cancel_btn.setMinimumHeight(36)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        # 版本提示
        ver_label = QLabel(f"版本 {VERSION}")
        ver_label.setAlignment(Qt.AlignCenter)
        ver_label.setStyleSheet("color: #6a6e7a; font-size: 10px; margin-top: 10px;")
        main_layout.addWidget(ver_label)
        
        self.setLayout(main_layout)
        
        # 连接信号
        self.start_btn.clicked.connect(self.on_start_clicked)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
    
    def on_start_clicked(self):
        """启动按钮处理：验证房间号并保存配置"""
        room_text = self.room_edit.text().strip()
        if not room_text:
            QMessageBox.warning(self, "输入错误", "请输入房间号")
            return
        
        try:
            room_val = int(room_text)
            if not (1 <= room_val <= 100):
                QMessageBox.warning(self, "输入错误", "房间号必须在 1-100 之间")
                return
        except ValueError:
            QMessageBox.warning(self, "输入错误", "房间号必须为整数")
            return
        
        if self.radio_main.isChecked():
            mode = "main"
        elif self.radio_backup.isChecked():
            mode = "backup"
        else:
            mode = "both"
        
        # 获取显示模式
        if self.radio_window.isChecked():
            display_mode = "window"
        else:
            display_mode = "notification"
        
        self.room_id = room_val
        self.mode = mode
        self.display_mode = display_mode
        # 透明度、字号、宽高比使用默认值（注意字号默认10，比例9:16）
        self.opacity = 0.85
        self.font_size = 10      # 默认字号减小
        self.aspect_ratio = "9:16"
        
        self.accept()   # 关闭对话框并返回 Accepted
    
    def on_cancel_clicked(self):
        """退出程序"""
        self.reject()

# ==================== 设置对话框（用于主悬浮窗） ====================
class SettingsDialog(QDialog):
    """设置对话框：调节透明度、字号、宽高比、窗口大小（等比缩放）"""
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window  # DanmakuWindow 实例
        self.setWindowTitle("悬浮窗设置")
        self.setModal(True)
        self.setFixedSize(400, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QRadioButton {
                color: #ffffff;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #2c3348;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #7c9cbf;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #2c3348;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #3a425c;
            }
            QGroupBox {
                border: 1px solid #2c3348;
                border-radius: 6px;
                margin-top: 10px;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 透明度
        opacity_group = QGroupBox("窗口透明度")
        opacity_layout = QVBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(int(self.parent_window.opacity_value * 100))
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        self.opacity_label = QLabel(f"当前: {self.opacity_slider.value()}%")
        opacity_layout.addWidget(self.opacity_label)
        opacity_group.setLayout(opacity_layout)
        layout.addWidget(opacity_group)
        
        # 字号
        font_group = QGroupBox("弹幕字号")
        font_layout = QVBoxLayout()
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(4, 24)
        self.font_slider.setValue(self.parent_window.current_font_size)
        self.font_slider.valueChanged.connect(self.on_font_changed)
        font_layout.addWidget(self.font_slider)
        self.font_label = QLabel(f"当前: {self.font_slider.value()}px")
        font_layout.addWidget(self.font_label)
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)
        
        # 宽高比
        ratio_group = QGroupBox("悬浮窗宽高比")
        ratio_layout = QVBoxLayout()
        ratio_radio_layout = QHBoxLayout()
        self.radio_16_9 = QRadioButton("16:9")
        self.radio_9_16 = QRadioButton("9:16")
        if self.parent_window.current_aspect_ratio == "16:9":
            self.radio_16_9.setChecked(True)
        else:
            self.radio_9_16.setChecked(True)
        self.radio_16_9.toggled.connect(self.on_ratio_changed)
        self.radio_9_16.toggled.connect(self.on_ratio_changed)
        ratio_radio_layout.addWidget(self.radio_16_9)
        ratio_radio_layout.addWidget(self.radio_9_16)
        ratio_radio_layout.addStretch()
        ratio_layout.addLayout(ratio_radio_layout)
        ratio_group.setLayout(ratio_layout)
        layout.addWidget(ratio_group)
        
        # 窗口大小调节（等比缩放）
        size_group = QGroupBox("窗口大小（等比缩放）")
        size_layout = QVBoxLayout()
        
        # 宽度调节滑块
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("宽度:"))
        self.width_slider = QSlider(Qt.Horizontal)
        # 宽度范围：最小宽度 ~ 屏幕宽度
        min_w = self.parent_window.min_width
        max_w = QApplication.primaryScreen().geometry().width() - 100
        self.width_slider.setRange(min_w, max_w)
        self.width_slider.setValue(self.parent_window.width())
        self.width_slider.valueChanged.connect(self.on_width_changed)
        width_layout.addWidget(self.width_slider)
        self.width_value_label = QLabel(f"{self.parent_window.width()}px")
        width_layout.addWidget(self.width_value_label)
        size_layout.addLayout(width_layout)
        
        # 高度显示（只读）
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("高度:"))
        self.height_value_label = QLabel(f"{self.parent_window.height()}px")
        height_layout.addWidget(self.height_value_label)
        height_layout.addStretch()
        size_layout.addLayout(height_layout)
        
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
    
    def on_opacity_changed(self, value):
        opacity = value / 100.0
        self.parent_window.set_opacity(opacity)
        self.opacity_label.setText(f"当前: {value}%")
    
    def on_font_changed(self, value):
        self.parent_window.set_font_size(value)
        self.font_label.setText(f"当前: {value}px")
    
    def on_ratio_changed(self):
        if self.radio_16_9.isChecked():
            new_ratio = "16:9"
        else:
            new_ratio = "9:16"
        self.parent_window.set_aspect_ratio(new_ratio)
        min_w = self.parent_window.min_width
        max_w = self.width_slider.maximum()
        self.width_slider.setRange(min_w, max_w)
        current_width = self.parent_window.width()
        if current_width < min_w:
            current_width = min_w
        self.parent_window.set_window_width(current_width)
        self.width_slider.setValue(current_width)
        self.width_value_label.setText(f"{current_width}px")
        self.height_value_label.setText(f"{self.parent_window.height()}px")
    
    def on_width_changed(self, width):
        self.parent_window.set_window_width(width)
        self.width_value_label.setText(f"{width}px")
        self.height_value_label.setText(f"{self.parent_window.height()}px")
    
    def showEvent(self, event):
        self.opacity_slider.setValue(int(self.parent_window.opacity_value * 100))
        self.font_slider.setValue(self.parent_window.current_font_size)
        if self.parent_window.current_aspect_ratio == "16:9":
            self.radio_16_9.setChecked(True)
        else:
            self.radio_9_16.setChecked(True)
        self.width_slider.setValue(self.parent_window.width())
        self.width_slider.setRange(self.parent_window.min_width, self.width_slider.maximum())
        self.width_value_label.setText(f"{self.parent_window.width()}px")
        self.height_value_label.setText(f"{self.parent_window.height()}px")
        super().showEvent(event)

    # 新增：从主窗口同步当前字号并更新UI
    def refresh_font_display(self):
        """从主窗口同步当前字号并更新滑块和标签"""
        current_size = self.parent_window.current_font_size
        self.font_slider.setValue(current_size)
        self.font_label.setText(f"当前: {current_size}px")

# ==================== 弹幕接收线程（异步） ====================
class DanmakuReceiver(QThread):
    """在独立线程中运行 asyncio 事件循环，接收弹幕并通过信号发送到主窗口"""
    new_danmaku = pyqtSignal(str, str)  # 用户名, 弹幕内容
    
    def __init__(self, room_id: int, mode: str):
        super().__init__()
        self.room_id = room_id
        self.mode = mode
        self.exit_event = threading.Event()
        self.loop = None
    
    def stop(self):
        self.exit_event.set()
        global active_websockets
        with ws_lock:
            for ws in active_websockets:
                if self.loop and self.loop.is_running():
                    asyncio.run_coroutine_threadsafe(ws.close(), self.loop)
            active_websockets.clear()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
    
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.main_async())
        except asyncio.CancelledError:
            logger.info("异步任务被取消")
        except Exception as e:
            logger.error(f"异步任务异常: {e}")
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
            logger.info("事件循环已关闭")
    
    async def handle_message(self, message: str):
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            if msg_type == "danmaku":
                danmaku = data.get("data", {})
                user = danmaku.get("user", "匿名")
                text = danmaku.get("text", "")
                self.new_danmaku.emit(user, text)
            elif msg_type == "init":
                logger.info("收到 init 消息（忽略）")
            else:
                logger.debug(f"未知消息类型: {msg_type}")
        except json.JSONDecodeError:
            logger.error(f"解析消息失败: {message}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}")
    
    async def websocket_task(self, url: str, name: str):
        global active_websockets
        while not self.exit_event.is_set():
            websocket = None
            try:
                async with websockets.connect(url) as websocket:
                    with ws_lock:
                        active_websockets.append(websocket)
                    logger.info(f"[{name}] 已连接到 {url}")
                    
                    join_msg = {
                        "type": "join",
                        "room": self.room_id,
                        "user": "客户端用户"
                    }
                    await websocket.send(json.dumps(join_msg))
                    
                    init_msg = await websocket.recv()
                    logger.info(f"[{name}] 收到 init: {init_msg[:100]}")
                    
                    async for message in websocket:
                        if self.exit_event.is_set():
                            break
                        await self.handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                if not self.exit_event.is_set():
                    logger.warning(f"[{name}] 连接已关闭，5秒后重连...")
            except Exception as e:
                if not self.exit_event.is_set():
                    logger.error(f"[{name}] 连接错误: {e}，5秒后重连...")
            finally:
                if websocket:
                    with ws_lock:
                        if websocket in active_websockets:
                            active_websockets.remove(websocket)
            
            if not self.exit_event.is_set():
                await asyncio.sleep(5)
        
        logger.info(f"[{name}] WebSocket 任务已退出")
    
    async def main_async(self):
        MAIN_URL = "wss://api.rrrosmontis.icu/v1/live/danmaku"
        BACKUP_URL = "wss://tsk.aeolianchi.me/danmaku"
        
        tasks = []
        if self.mode == "main":
            tasks.append(self.websocket_task(MAIN_URL, "主站"))
        elif self.mode == "backup":
            tasks.append(self.websocket_task(BACKUP_URL, "副站"))
        elif self.mode == "both":
            tasks.append(self.websocket_task(MAIN_URL, "主站"))
            tasks.append(self.websocket_task(BACKUP_URL, "副站"))
        else:
            logger.error(f"未知模式: {self.mode}")
            return
        
        await asyncio.gather(*tasks, return_exceptions=True)

# ==================== 弹幕条目控件（支持动画） ====================
class DanmakuItem(QLabel):
    """单个弹幕的显示控件，支持淡入动画"""
    def __init__(self, user: str, text: str, font_size: int, parent=None):
        super().__init__(parent)
        html = f'<div style="word-wrap: break-word; white-space: normal; max-width: 100%;"><span style="color:#5DA2E2;">{user}:</span> <span style="color:#f0f0f0;">{text}</span></div>'
        self.setText(html)
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        font = QFont("Microsoft YaHei", font_size)
        self.setFont(font)
        self.setContentsMargins(4, 2, 4, 2)
        self.setStyleSheet("""
            QLabel {
                background-color: rgba(30, 30, 40, 100);
                border-radius: 6px;
                padding: 4px 6px;
            }
        """)
        self.opacity_effect = None
        self.animation = None
    
    def start_animation(self):
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.start()

# ==================== 主悬浮窗（无边框、可拖拽、等比例缩放、半透明） ====================
class DanmakuWindow(QWidget):
    def __init__(self, room_id: int, mode: str, opacity: float, font_size: int, aspect_ratio: str):
        super().__init__()
        self.room_id = room_id
        self.mode = mode
        self.opacity_value = opacity
        self.current_font_size = font_size
        self.current_aspect_ratio = aspect_ratio  # "16:9" 或 "9:16"
        self.dragging = False
        self.drag_pos = None
        self.receiver = None
        self._updating_scaling = False
        self.settings_dialog = None   # 记录设置对话框实例，用于同步字号
        
        self.update_min_size()
        if self.current_aspect_ratio == "16:9":
            self.base_width = 350   # 减小默认宽度
            self.base_height = int(350 * 9 / 16)
        else:
            self.base_width = 250   # 9:16 默认宽度更小
            self.base_height = int(250 * 16 / 9)
        if self.base_width < self.min_width:
            self.base_width = self.min_width
            self.base_height = int(self.base_width * (9/16 if self.current_aspect_ratio == "16:9" else 16/9))
        
        self.init_ui()
        
        # 窗口标志：无边框、置顶、工具窗口（隐藏任务栏）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(self.opacity_value)
        
        self.resize(self.base_width, self.base_height)
        self.center()
        
        self._resizing = False
        self.update_ui_scaling()
    
    def update_min_size(self):
        if self.current_aspect_ratio == "16:9":
            self.min_width = 150
            self.min_height = int(150 * 9 / 16)
        else:
            self.min_width = 100
            self.min_height = int(100 * 16 / 9)
    
    def center(self):
        screen_geo = QApplication.primaryScreen().geometry()
        x = (screen_geo.width() - self.width()) // 2
        y = (screen_geo.height() - self.height()) // 2
        self.move(x, y)
    
    def init_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet("""
            QFrame#Container {
                background-color: rgba(20, 20, 30, 255);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
            QLabel {
                color: #f0f0f0;
                background: transparent;
            }
        """)
        
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(8, 12, 8, 12)
        main_layout.setSpacing(8)
        
        self.title_layout = QVBoxLayout()
        self.title_layout.setSpacing(4)
        
        first_row = QHBoxLayout()
        self.title_label1 = QLabel("弹幕列表")
        self.title_label1.setStyleSheet("font-weight: bold; color: #d4d4d4;")
        first_row.addWidget(self.title_label1)
        first_row.addStretch()
        
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background: rgba(80, 80, 90, 150);
                border-radius: 12px;
                font-weight: bold;
                color: #c0c0c0;
            }
            QPushButton:hover {
                background: rgba(120, 120, 130, 200);
                color: white;
            }
        """)
        self.settings_btn.clicked.connect(self.open_settings)
        first_row.addWidget(self.settings_btn)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(80, 80, 90, 150);
                border-radius: 12px;
                font-weight: bold;
                color: #c0c0c0;
            }
            QPushButton:hover {
                background: rgba(120, 120, 130, 200);
                color: white;
            }
        """)
        self.close_btn.clicked.connect(self.close_app)
        first_row.addWidget(self.close_btn)
        
        self.title_layout.addLayout(first_row)
        
        mode_text = ""
        if self.mode == "main":
            mode_text = "SITE 1"
        elif self.mode == "backup":
            mode_text = "SITE 2"
        else:
            mode_text = "SITE 1 & 2"
        self.title_label2 = QLabel(f"{mode_text} · ROOM {self.room_id}")
        self.title_label2.setStyleSheet("color: #a0a0c0;")
        self.title_layout.addWidget(self.title_label2)
        main_layout.addLayout(self.title_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: rgba(255, 255, 255, 40); max-height: 1px;")
        main_layout.addWidget(line)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget {
                background: transparent;
            }
        """)
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        
        self.danmaku_container = QWidget()
        self.danmaku_container.setStyleSheet("background: transparent;")
        self.danmaku_layout = QVBoxLayout(self.danmaku_container)
        self.danmaku_layout.setAlignment(Qt.AlignTop)
        self.danmaku_layout.setSpacing(6)
        self.danmaku_layout.setContentsMargins(2, 4, 2, 4)
        self.scroll_area.setWidget(self.danmaku_container)
        
        main_layout.addWidget(self.scroll_area)
        
        self.container.setGeometry(0, 0, self.width(), self.height())
        self.container.setLayout(main_layout)
    
    def update_ui_scaling(self):
        if self._updating_scaling:
            return
        self._updating_scaling = True
        base_width = 500
        scale = self.width() / base_width
        scale = max(0.5, min(1.5, scale))
        
        title_font_size = int(16 * scale)
        title_font = QFont("Microsoft YaHei", title_font_size)
        title_font.setBold(True)
        self.title_label1.setFont(title_font)
        
        subtitle_font_size = int(11 * scale)
        subtitle_font = QFont("Microsoft YaHei", subtitle_font_size)
        self.title_label2.setFont(subtitle_font)
        
        btn_size = int(24 * scale)
        btn_font_size = int(14 * scale)
        self.settings_btn.setFixedSize(btn_size, btn_size)
        self.close_btn.setFixedSize(btn_size, btn_size)
        
        btn_font = QFont("Segoe UI", btn_font_size)
        self.settings_btn.setFont(btn_font)
        self.close_btn.setFont(btn_font)
        
        self.title_layout.setSpacing(int(4 * scale))
        self._updating_scaling = False
    
    def open_settings(self):
        if self.settings_dialog is None:
            dlg = SettingsDialog(self)
            self.settings_dialog = dlg
            dlg.finished.connect(lambda: setattr(self, 'settings_dialog', None))
            dlg.show()
        else:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
    
    def set_opacity(self, value):
        self.opacity_value = value
        self.setWindowOpacity(value)
    
    def set_font_size(self, size):
        self.current_font_size = size
        font = QFont("Microsoft YaHei", size)
        for i in range(self.danmaku_layout.count()):
            item = self.danmaku_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                widget.setFont(font)
                widget.updateGeometry()
        self.danmaku_layout.invalidate()
        self.danmaku_container.updateGeometry()
        self.scroll_area.updateGeometry()
        self.scroll_to_bottom()

        # 如果设置对话框已打开，同步其显示
        if self.settings_dialog is not None:
            self.settings_dialog.refresh_font_display()
    
    def set_aspect_ratio(self, ratio):
        if ratio == self.current_aspect_ratio:
            return
        self.current_aspect_ratio = ratio
        self.update_min_size()
        self.set_window_width(self.width())
    
    def set_window_width(self, width):
        if width < self.min_width:
            width = self.min_width
        if self.current_aspect_ratio == "16:9":
            height = int(width * 9 / 16)
        else:
            height = int(width * 16 / 9)
        if height < self.min_height:
            height = self.min_height
            width = int(height * (16/9 if self.current_aspect_ratio == "16:9" else 9/16))
        self.resize(width, height)
    
    def add_danmaku(self, user: str, text: str):
        """添加一条弹幕，并强制滚动到底部（修复留白和显示不全问题）"""
        if not self.isVisible():
            return
        item = DanmakuItem(user, text, self.current_font_size)
        self.danmaku_layout.addWidget(item)
        item.start_animation()
        
        # 延迟滚动，确保布局完全更新（避免留白/显示不全）
        QTimer.singleShot(30, self.scroll_to_bottom)
        
        # 限制最大条目数
        if self.danmaku_layout.count() > 200:
            oldest_item = self.danmaku_layout.takeAt(0)
            if oldest_item.widget():
                oldest_item.widget().deleteLater()
    
    def scroll_to_bottom(self):
        """滚动到底部，强制更新滚动条最大值"""
        scrollbar = self.scroll_area.verticalScrollBar()
        # 先强制刷新布局，确保最大值正确
        self.danmaku_container.updateGeometry()
        self.scroll_area.updateGeometry()
        scrollbar.setValue(scrollbar.maximum())
    
    def close_app(self):
        if self.receiver:
            try:
                self.receiver.new_danmaku.disconnect(self.add_danmaku)
            except (TypeError, AttributeError):
                pass
        exit_event.set()
        if self.receiver and self.receiver.isRunning():
            self.receiver.stop()
            self.receiver.wait(3000)
        QApplication.quit()
    
    # ========== 无边框窗口拖拽和等比例缩放 ==========
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if event.pos().y() < 60:
                self.dragging = True
                self.drag_pos = event.globalPos()
                event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and self.drag_pos is not None:
            delta = event.globalPos() - self.drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.drag_pos = event.globalPos()
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        self.dragging = False
        self.drag_pos = None
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.pos().y() < 60:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

    def update_danmaku_max_width(self):
        """根据当前视口宽度，限制所有弹幕条目的最大宽度"""
        # 获取视口宽度（滚动区域内部可用宽度）
        viewport_width = self.scroll_area.viewport().width()
        # 减去 danmaku_layout 的左右边距（2+2=4）以及容器内边距
        max_width = viewport_width - 8  # 左右各2px边距，再留一点余量
        if max_width < 50:
            max_width = 50
        for i in range(self.danmaku_layout.count()):
            item = self.danmaku_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                widget.setMaximumWidth(max_width)
                # 强制重新布局，确保换行生效
                widget.updateGeometry()

    def auto_adjust_font_size(self):
        """根据当前窗口宽度自动计算并调整弹幕字号"""
        width = self.width()
        new_size = int(width * 0.04)           # 线性关系：宽度250 -> 字号10
        new_size = max(4, min(24, new_size))   # 限制字号范围 4~24
        if new_size != self.current_font_size:
            self.set_font_size(new_size)
    
    def resizeEvent(self, event: QResizeEvent):
        if not self._resizing and not self.isMaximized():
            self._resizing = True
            if self.current_aspect_ratio == "16:9":
                target_ratio = 16 / 9
            else:
                target_ratio = 9 / 16
            
            new_width = event.size().width()
            new_height = event.size().height()
            current_ratio = new_width / new_height
            
            if abs(current_ratio - target_ratio) > 0.01:
                if current_ratio > target_ratio:
                    new_width = int(new_height * target_ratio)
                else:
                    new_height = int(new_width / target_ratio)
                new_width = max(self.min_width, new_width)
                new_height = max(self.min_height, new_height)
                self.resize(new_width, new_height)
                event.accept()
            
            self.container.setGeometry(0, 0, self.width(), self.height())
            self._resizing = False
        elif self.isMaximized():
            self.container.setGeometry(0, 0, self.width(), self.height())
        
        self.update_ui_scaling()
        self.update_danmaku_max_width()
        self.auto_adjust_font_size() 
        super().resizeEvent(event)

# ==================== 系统通知发送函数（静音） ====================
def send_notification(title: str, main_content: str, sub_content: str = ""):
    """在独立线程中发送 Windows 通知（避免 Qt 事件循环冲突）"""
    def _show():
        pythoncom.CoInitialize()  # 初始化 COM 为 STA
        notification = Notification(
            app_id="TSUKUYOMI DANMAKU",
            title=title,
            msg=main_content,
            duration="short"
        )
        if sub_content:
            notification.msg = f"{main_content}\n{sub_content}"
        # 暂时注释掉 set_audio，避免未知干扰
        # notification.set_audio(audio.Silent, loop=False)
        notification.show()
        pythoncom.CoUninitialize()

    threading.Thread(target=_show, daemon=True).start()

# ==================== 托盘图标相关 ====================
def setup_tray(quit_callback, icon_image):
    menu = pystray.Menu(pystray.MenuItem("退出", quit_callback))
    icon = pystray.Icon("danmaku_client", icon_image, "TSUKUYOMI DANMAKU", menu)
    tray_thread = threading.Thread(target=icon.run, daemon=True)
    tray_thread.start()
    return icon, tray_thread

# ==================== 主函数 ====================
def main():
    if sys.platform != "win32":
        logger.error("此客户端仅在 Windows 上支持系统通知，请使用其他方式")
        sys.exit(1)
    
    # 启用高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    # 设置应用图标（任务栏）
    app_icon = get_qicon()
    app.setWindowIcon(app_icon)
    
    # 显示配置对话框（模态）
    config_dialog = ConfigDialog()
    if config_dialog.exec_() != QDialog.Accepted:
        logger.info("用户取消配置，退出程序")
        sys.exit(0)
    
    room_id = config_dialog.room_id
    mode = config_dialog.mode
    opacity = config_dialog.opacity
    font_size = config_dialog.font_size
    aspect_ratio = config_dialog.aspect_ratio
    display_mode = config_dialog.display_mode  # "window" 或 "notification"
    
    # 创建弹幕接收线程（两种模式都需要）
    receiver = DanmakuReceiver(room_id, mode)
    
    # 托盘图标图片（提前加载）
    tray_icon_img = get_icon_image()
    
    # 根据显示模式创建不同的 UI 组件
    if display_mode == "window":
        # 悬浮窗模式
        main_window = DanmakuWindow(room_id, mode, opacity, font_size, aspect_ratio)
        main_window.show()
        receiver.new_danmaku.connect(main_window.add_danmaku)
        main_window.receiver = receiver
        # 退出回调
        def on_quit(icon=None, item=None):
            logger.info("正在安全退出...")
            exit_event.set()
            try:
                receiver.new_danmaku.disconnect(main_window.add_danmaku)
            except TypeError:
                pass
            receiver.stop()
            receiver.wait(3000)
            if icon:
                icon.stop()
            QApplication.quit()
        # 替换 close_app 方法
        main_window.close_app = lambda: on_quit()
        # 设置 app 在最后一个窗口关闭时退出（悬浮窗关闭即退出）
        app.setQuitOnLastWindowClosed(True)
    else:
        # 通知模式：不创建悬浮窗，只使用系统通知
        # 禁止窗口关闭时退出程序（因为没有主窗口）
        app.setQuitOnLastWindowClosed(False)
        
        # 发送启动通知
        mode_text = ""
        if mode == "main":
            mode_text = "SITE 1"
        elif mode == "backup":
            mode_text = "SITE 2"
        else:
            mode_text = "SITE 1 & 2"
        send_notification(
            title="TSUKUYOMI DANMAKU",
            main_content="弹幕接收已开启。右键托盘图标可关闭",
            sub_content=f"{mode_text} · ROOM {room_id}"
        )
        
        # 连接弹幕信号到通知函数
        def on_new_danmaku(user, text):
            send_notification(
                title=text,                      # 弹幕内容作为标题
                main_content=f"来自 {user}",     # 发送者信息作为正文
                sub_content=""                  # 无需副内容
            )
        receiver.new_danmaku.connect(on_new_danmaku)
        
        # 退出回调
        def on_quit(icon=None, item=None):
            logger.info("正在安全退出...")
            exit_event.set()
            receiver.stop()
            receiver.wait(3000)
            if icon:
                icon.stop()
            QApplication.quit()
    
    # 启动接收线程
    receiver.start()
    
    # 创建托盘图标（两种模式都需要）
    tray_icon, tray_thread = setup_tray(on_quit, tray_icon_img)
    
    # 运行 Qt 主循环
    try:
        sys.exit(app.exec_())
    except SystemExit:
        pass
    finally:
        if receiver.isRunning():
            receiver.stop()
            receiver.wait(2000)
        if tray_thread.is_alive():
            tray_thread.join(timeout=1)
        logger.info("程序已完全退出")

if __name__ == "__main__":
    main()