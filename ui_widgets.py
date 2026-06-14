import time
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsItem, QGraphicsTextItem, QWidget
from PyQt6.QtGui import QBrush, QPen, QColor, QPainter, QFont, QPainterPath, QPolygon
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QTimer, QPoint

TRACK_COLORS = [
    "#5e81ac", "#81a1c1", "#88c0d0", "#8fbcbb", "#b48ead",
    "#a3be8c", "#ebcb8b", "#d08770", "#bf616a", "#4c566a",
    "#434c5e", "#3b4252", "#2e3440", "#d8dee9", "#e5e9f0"
]
MOTOR_COLOR = "#88c0d0"

class NoteGraphicItem(QGraphicsRectItem):
    """可拖曳、改變長度與視覺化標記的音符方塊"""
    def __init__(self, note_data, x, y, w, h, view):
        super().__init__(x, y, w, h)
        self.note_data = note_data
        self.view = view
        
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        
        self.route_label = QGraphicsTextItem(self)
        self.route_label.setFont(QFont("Arial", 7, QFont.Weight.Bold))
        self.route_label.setDefaultTextColor(QColor("white"))
        self.route_label.setPos(2, -2)
        
        self.update_visuals()

    def update_visuals(self):
        if hasattr(self.note_data, 'is_motor') and self.note_data.is_motor:
            color = QColor(MOTOR_COLOR)
        elif hasattr(self.note_data, 'track_id') and 0 <= self.note_data.track_id < 15:
            color = QColor(TRACK_COLORS[self.note_data.track_id])
        else:
            color = QColor("#9ca3af") 

        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(150), 1))

    def update_geometry(self, zoom_x, note_height):
        x = (self.note_data.t_note_us / 1_000_000) * zoom_x
        y = (127 - self.note_data.pitch) * note_height
        duration = getattr(self.note_data, 'duration_us', 200_000)
        w = max((duration / 1_000_000) * zoom_x, 3)
        h = note_height
        self.setRect(x, y, w, h)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            # Intelligent selection: clear other selections if right-clicked note isn't selected
            if not self.isSelected():
                self.scene().clearSelection()
                self.setSelected(True)
            
            # Call context menu callback
            if getattr(self.view, 'context_menu_cb', None):
                self.view.context_menu_cb(self, self.note_data)
            
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        
        # Support group dragging by collecting all selected notes' new coordinates
        changes = []
        if self.isSelected():
            for item in self.scene().selectedItems():
                if isinstance(item, NoteGraphicItem):
                    new_x = item.x() + item.rect().x()
                    new_y = item.y() + item.rect().y()
                    new_t = max(0, int((new_x / item.view.zoom_x) * 1_000_000))
                    new_p = max(0, min(127, 127 - int(new_y / item.view.note_height)))
                    changes.append((item.note_data, new_p, new_t))
        else:
            new_x = self.x() + self.rect().x()
            new_y = self.y() + self.rect().y()
            new_t = max(0, int((new_x / self.view.zoom_x) * 1_000_000))
            new_p = max(0, min(127, 127 - int(new_y / self.view.note_height)))
            changes.append((self.note_data, new_p, new_t))
            
        if getattr(self.view, 'notes_changed_cb', None):
            self.view.notes_changed_cb(changes)

    def paint(self, painter, option, widget):
        rect = self.boundingRect()
        color = self.brush().color()
        if self.isSelected():
            color = color.lighter(130)
            painter.setPen(QPen(QColor("#ffffff"), 1))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(rect, 4, 4)

class PianoRollView(QGraphicsView):
    note_added_sig = pyqtSignal(int, int)
    sig_playhead_moved = pyqtSignal(int)
    sig_loop_region_changed = pyqtSignal(int, int)
    sig_zoom_changed = pyqtSignal(float)
    
    # Show safe zone toggle
    def __init__(self, show_safe_zone=False):
        super().__init__()
        self.show_safe_zone = show_safe_zone
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        self.zoom_x = 100 
        self.note_height = 20
        self.max_time_us = 10_000_000 
        
        self.notes_changed_cb = None
        self.context_menu_cb = None
        
        self.playhead = self.scene.addLine(0, 0, 0, 128 * self.note_height, QPen(QColor("#0a84ff"), 2))
        self.playhead.setZValue(100)
        self.loop_region_item = self.scene.addRect(0, 0, 0, 128 * self.note_height, QPen(Qt.PenStyle.NoPen), QBrush(QColor(234, 179, 8, 40)))
        self.loop_region_item.setZValue(-5)
        self.loop_start_us = 0
        self.loop_end_us = 0
        
        self.grid_lines = [] 
        
        self.update_scene_rect()
        
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#1e1e1e")))
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        
        self._is_panning = False
        self._pan_start_x = 0

    def select_all(self):
        for item in self.scene.items():
            if isinstance(item, NoteGraphicItem):
                item.setSelected(True)
        
    def update_scene_rect(self):
        width = (self.max_time_us / 1_000_000) * self.zoom_x
        height = 128 * self.note_height
        self.scene.setSceneRect(0, 0, max(1000, width), height)
        self._draw_grid()

    def _draw_grid(self):
        """繪製並刷新背景格線"""
        for line in self.grid_lines:
            self.scene.removeItem(line)
        self.grid_lines.clear()
                
        width = self.scene.width()
        height = self.scene.height()
        
        # Only draw safe zone if enabled
        if self.show_safe_zone:
            y_top = (127 - 103) * self.note_height
            safe_height = (103 - 79 + 1) * self.note_height
            
            safe_bg = self.scene.addRect(0, y_top, width, safe_height, QPen(Qt.PenStyle.NoPen), QBrush(QColor(16, 185, 129, 20)))
            safe_bg.setZValue(-2) 
            self.grid_lines.append(safe_bg)
            
            pen_border = QPen(QColor("#10b981"), 2, Qt.PenStyle.DashLine)
            safe_border = self.scene.addRect(0, y_top, width, safe_height, pen_border, QBrush(Qt.BrushStyle.NoBrush))
            safe_border.setZValue(-1)
            self.grid_lines.append(safe_border)
            
            text = self.scene.addText("鐵琴專屬安全音域 (G5 ~ G7) - 移入此框由鐵琴發聲，框外及黑鍵由馬達代打", QFont("Arial", 10, QFont.Weight.Bold))
            text.setDefaultTextColor(QColor("#10b981"))
            text.setPos(10, y_top + 5)
            text.setZValue(-1)
            self.grid_lines.append(text)
        # ==========================================
        
        # Draw piano keys background (light/dark alternating)
        black_keys_pattern = {1, 3, 6, 8, 10}
        for i in range(128):
            pitch = 127 - i
            y = i * self.note_height
            is_black_key = (pitch % 12) in black_keys_pattern
            
            bg_color = QColor("#1a1a1a") if is_black_key else QColor("#242424")
            rect = self.scene.addRect(0, y, max(width, 2000), self.note_height, QPen(Qt.PenStyle.NoPen), QBrush(bg_color))
            rect.setZValue(-3)
            self.grid_lines.append(rect)
            
            # Subdued horizontal divider
            line = self.scene.addLine(0, y, max(width, 2000), y, QPen(QColor("#2c2c2e"), 1))
            line.setZValue(-2)
            self.grid_lines.append(line)
            
        # Draw vertical beats
        beat_width = (500_000 / 1_000_000) * self.zoom_x
        x = 0
        tick_count = 0
        while x < max(width, 2000):
            pen = QPen(QColor("#404040"), 1) if tick_count % 2 == 0 else QPen(QColor("#2a2a2a"), 1)
            line = self.scene.addLine(x, 0, x, height, pen)
            line.setZValue(-2)
            self.grid_lines.append(line)
            x += beat_width
            tick_count += 1

    def load_notes(self, notes, changed_cb=None, context_menu_cb=None):
        self.notes_changed_cb = changed_cb
        self.context_menu_cb = context_menu_cb
        self.clear_notes()
        
        if not notes: return
            
        last_note_time = max(n.t_note_us for n in notes)
        if last_note_time > self.max_time_us:
            self.max_time_us = last_note_time + 2_000_000 
            self.update_scene_rect()
            
        for n in notes:
            x = (n.t_note_us / 1_000_000) * self.zoom_x
            pitch_to_draw = getattr(n, 'effective_pitch', n.pitch)
            y = (127 - pitch_to_draw) * self.note_height
            duration = getattr(n, 'duration_us', 200_000)
            w = max((duration / 1_000_000) * self.zoom_x, 3)
            h = self.note_height
            
            item = NoteGraphicItem(n, x, y, w, h, self)
            self.scene.addItem(item)

    def clear_notes(self):
        for item in self.scene.items():
            if isinstance(item, NoteGraphicItem):
                self.scene.removeItem(item)

    def update_playhead(self, current_time_us):
        x = (current_time_us / 1_000_000) * self.zoom_x
        self.playhead.setLine(x, 0, x, 128 * self.note_height)
        
        rect = self.viewport().rect()
        scene_pos = self.mapToScene(rect)
        if x > scene_pos[1].x() - 50: 
            self.horizontalScrollBar().setValue(int(x - rect.width() / 2))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            t_us = int((scene_pos.x() / self.zoom_x) * 1_000_000)
            pitch = 127 - int(scene_pos.y() / self.note_height)
            self.note_added_sig.emit(pitch, t_us) 
        super().mouseDoubleClickEvent(event)
        
    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        t_us = max(0, int((scene_pos.x() / self.zoom_x) * 1_000_000))
        
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            if event.button() == Qt.MouseButton.LeftButton:
                self.loop_start_us = t_us
            elif event.button() == Qt.MouseButton.RightButton:
                self.loop_end_us = t_us
            
            if self.loop_end_us > self.loop_start_us:
                start_x = (self.loop_start_us / 1_000_000) * self.zoom_x
                end_x = (self.loop_end_us / 1_000_000) * self.zoom_x
                self.loop_region_item.setRect(start_x, 0, end_x - start_x, 128 * self.note_height)
                self.sig_loop_region_changed.emit(self.loop_start_us, self.loop_end_us)
            else:
                self.loop_region_item.setRect(0, 0, 0, 128 * self.note_height)
                self.sig_loop_region_changed.emit(0, 0)
            event.accept()
            return
            
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag) 
            self._is_panning = True
            self._pan_start_x = event.pos().x()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
            
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if not item:
                self.sig_playhead_moved.emit(t_us)
                
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag) 
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            dx = self._pan_start_x - event.pos().x()
            self._pan_start_x = event.pos().x()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            event.accept()
        else:
            super().mouseMoveEvent(event)
            
    def set_zoom(self, zoom_x):
        if self.zoom_x == zoom_x: return
        self.zoom_x = zoom_x
        self.update_scene_rect()
        for item in self.scene.items():
            if isinstance(item, NoteGraphicItem):
                item.update_geometry(self.zoom_x, self.note_height)
        self.sig_zoom_changed.emit(self.zoom_x)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            zoom_factor = 1.1 if event.angleDelta().y() > 0 else 0.9
            new_zoom = max(20, min(1500, self.zoom_x * zoom_factor))
            self.set_zoom(new_zoom)
            event.accept()
        else:
            delta_x = event.angleDelta().y() / 2
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta_x))
            event.accept()

class PianoKeyboardWidget(QWidget):
    """橫向 88 鍵鋼琴視覺模擬器 (保持不變)"""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        self.active_keys = {} 
        
        self.start_pitch = 21
        self.end_pitch = 108
        self.white_keys_pattern = [0, 2, 4, 5, 7, 9, 11] 
        self.num_white_keys = sum(1 for p in range(self.start_pitch, self.end_pitch + 1) if p % 12 in self.white_keys_pattern)
        
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(30) 
        self.anim_timer.timeout.connect(self.update_animation)
        self.anim_timer.start()

    def press_key(self, pitch: int, is_ai: bool = False):
        if self.start_pitch <= pitch <= self.end_pitch:
            self.active_keys[pitch] = {"expire": time.perf_counter() + 0.3, "is_ai": is_ai}
            self.update()

    def release_key(self, pitch: int):
        if pitch in self.active_keys: del self.active_keys[pitch]; self.update()

    def update_animation(self):
        now = time.perf_counter()
        expired = [p for p, data in self.active_keys.items() if now > data["expire"]]
        if expired:
            for p in expired: del self.active_keys[p]
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width(); h = self.height()
        painter.fillRect(0, 0, w, h, QColor("#121212"))
        
        if self.num_white_keys == 0: return
        white_key_w = w / self.num_white_keys
        
        wk_idx = 0
        for p in range(self.start_pitch, self.end_pitch + 1):
            if p % 12 in self.white_keys_pattern:
                rect = QRectF(wk_idx * white_key_w, 0, white_key_w, h)
                is_active = p in self.active_keys
                color = QColor("#b48ead") if is_active and self.active_keys[p]["is_ai"] else QColor("#88c0d0") if is_active else QColor("#2e3440")
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor("#121212"), 1))
                painter.drawRect(rect)
                wk_idx += 1

        wk_idx = 0
        for p in range(self.start_pitch, self.end_pitch + 1):
            if p % 12 in self.white_keys_pattern: wk_idx += 1
            else:
                bw, bh = white_key_w * 0.65, h * 0.65
                bx = (wk_idx * white_key_w) - (bw / 2)
                rect = QRectF(bx, 0, bw, bh)
                is_active = p in self.active_keys
                color = QColor("#b48ead") if is_active and self.active_keys[p]["is_ai"] else QColor("#81a1c1") if is_active else QColor("#1c1c1e")
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                path = QPainterPath(); path.addRoundedRect(rect, 4, 4)
                painter.drawPath(path)

class TimeRulerWidget(QWidget):
    def __init__(self, target_view):
        super().__init__()
        self.setFixedHeight(24)
        self.view = target_view
        self.view.horizontalScrollBar().valueChanged.connect(self.update)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#121212"))
        
        scroll_x = self.view.horizontalScrollBar().value()
        zoom_x = self.view.zoom_x
        width = self.width()
        
        pen_tick = QPen(QColor("#666666"), 1)
        pen_text = QPen(QColor("#aaaaaa"))
        painter.setFont(QFont("Arial", 9))
        
        start_time_us = (scroll_x / zoom_x) * 1_000_000
        end_time_us = ((scroll_x + width) / zoom_x) * 1_000_000
        
        tick_interval_us = 1_000_000 if zoom_x < 50 else 500_000
        start_tick = int(start_time_us // tick_interval_us) * tick_interval_us
        
        t_us = start_tick
        while t_us <= end_time_us:
            x = int((t_us / 1_000_000) * zoom_x - scroll_x)
            
            if t_us % 1_000_000 == 0:
                painter.setPen(pen_text)
                sec = t_us // 1_000_000
                m = sec // 60
                s = sec % 60
                text = f"{m}:{s:02d}"
                painter.drawText(x + 3, 12, text)
                
                painter.setPen(pen_tick)
                painter.drawLine(x, 14, x, 24)
            else:
                painter.setPen(pen_tick)
                painter.drawLine(x, 18, x, 24)
                
            t_us += tick_interval_us
            
        # Draw playhead on ruler
        if hasattr(self.view, 'playhead') and self.view.playhead.isVisible():
            playhead_x = int(self.view.playhead.line().x1() - scroll_x)
            if 0 <= playhead_x <= width:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#0a84ff")))
                pts = [QPoint(playhead_x - 4, 16), QPoint(playhead_x + 4, 16), QPoint(playhead_x, 24)]
                painter.drawPolygon(QPolygon(pts))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scroll_x = self.view.horizontalScrollBar().value()
            zoom_x = self.view.zoom_x
            click_x = event.pos().x()
            
            t_us = max(0, int(((click_x + scroll_x) / zoom_x) * 1_000_000))
            self.view.sig_playhead_moved.emit(t_us)
            event.accept()
        else:
            super().mousePressEvent(event)