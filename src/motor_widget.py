import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QFont

class SciFiMotorWidget(QWidget):
    def __init__(self, motor_id):
        super().__init__()
        self.motor_id = motor_id
        self.hz = 0
        self.velocity = 0
        self.angle = 0
        self.is_alert = False

        self.setMinimumSize(140, 160)
        
        # 重繪計時器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_rotation)
        self.timer.start(16) 

        # 動畫引擎
        self._shake_offset = QPoint(0, 0)
        self._shake_anim = QPropertyAnimation(self, b"shake_offset")
        self._shake_anim.setEasingCurve(QEasingCurve.Type.InOutBounce)

    # 定義 Qt 屬性讓動畫引擎可以操作
    def get_shake_offset(self): return self._shake_offset
    def set_shake_offset(self, offset): 
        self._shake_offset = offset
        self.update()
    shake_offset = pyqtProperty(QPoint, get_shake_offset, set_shake_offset)

    def set_state(self, hz, velocity, is_alert=False):
        self.hz = hz
        self.velocity = velocity
        if is_alert and not self.is_alert:
            self.trigger_shake()
        self.is_alert = is_alert

    def update_rotation(self):
        if self.hz > 0:
            # 依據 Hz 計算旋轉角度
            self.angle = (self.angle + self.hz * 0.15) % 360
            self.update()
        elif self.angle != 0:
            self.update()

    def trigger_shake(self):
        """觸發危險共振時的劇烈物理抖動"""
        self._shake_anim.stop()
        self._shake_anim.setDuration(250)
        self._shake_anim.setKeyValueAt(0, QPoint(0, 0))
        self._shake_anim.setKeyValueAt(0.2, QPoint(6, -6))
        self._shake_anim.setKeyValueAt(0.4, QPoint(-6, 6))
        self._shake_anim.setKeyValueAt(0.6, QPoint(6, 6))
        self._shake_anim.setKeyValueAt(0.8, QPoint(-6, -6))
        self._shake_anim.setKeyValueAt(1, QPoint(0, 0))
        self._shake_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 加上偏移量
        cx = self.width() / 2 + self._shake_offset.x()
        cy = self.height() / 2 - 15 + self._shake_offset.y()
        radius = 45

        # 繪製光暈
        if self.hz > 0:
            glow_radius = radius + 15 + (self.velocity / 127.0) * 20
            grad = QRadialGradient(cx, cy, glow_radius)
            # 綠色與紅色
            base_color = QColor(225, 29, 72) if self.is_alert else QColor(16, 185, 129)
            grad.setColorAt(0, QColor(base_color.red(), base_color.green(), base_color.blue(), 120))
            grad.setColorAt(1, QColor(base_color.red(), base_color.green(), base_color.blue(), 0))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(cx), int(cy)), int(glow_radius), int(glow_radius))

        # 繪製外殼
        painter.setPen(QPen(QColor(51, 65, 85), 4))
        painter.setBrush(QBrush(QColor(15, 23, 42))) # 深色內部
        painter.drawEllipse(QPoint(int(cx), int(cy)), radius, radius)

        # 繪製轉子
        painter.translate(cx, cy)
        painter.rotate(self.angle)
        painter.setPen(QPen(QColor(148, 163, 184), 3))
        for _ in range(6): # 6 個齒輪
            painter.drawLine(0, -15, 0, -radius + 8)
            painter.rotate(60)
        painter.rotate(-self.angle)
        painter.translate(-cx, -cy)

        # 繪製文字
        font = painter.font()
        font.setBold(True)
        
        # 標籤
        font.setPointSize(12)
        painter.setFont(font)
        painter.setPen(QPen(QColor(241, 245, 249)))
        painter.drawText(int(cx - 14), int(cy + radius + 25), f"M{self.motor_id}")
        
        # Hz 數值
        font.setPointSize(10)
        painter.setFont(font)
        hz_text = f"{self.hz:.1f} Hz" if self.hz > 0 else "IDLE"
        if self.hz == 0:
            hz_color = QColor(100, 116, 139)
        else:
            hz_color = QColor(244, 63, 94) if self.is_alert else QColor(52, 211, 153)
            
        text_width = painter.fontMetrics().horizontalAdvance(hz_text)
        painter.setPen(QPen(hz_color))
        painter.drawText(int(cx - text_width/2), int(cy + radius + 45), hz_text)