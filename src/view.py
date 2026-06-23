from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, 
                             QLabel, QCheckBox, QTextEdit, QFileDialog, QComboBox, QLineEdit, QSlider, QMessageBox, QSplitter,
                             QDialog, QRadioButton, QGroupBox, QMenu)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QShortcut, QKeySequence, QColor, QBrush, QCursor
from PyQt6.QtWidgets import QGraphicsTextItem

from ui_widgets import PianoKeyboardWidget, PianoRollView, NoteGraphicItem, TRACK_COLORS, MOTOR_COLOR, TimeRulerWidget
from settings_ui import HardwareSettingsDialog
from motor_widget import SciFiMotorWidget
from core_logic import NoteData

class ImportMidiDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("匯入 MIDI 設定")
        self.resize(450, 300)
        if parent: self.setStyleSheet(parent.styleSheet())
        self.mode = "unified_ai"
        self.file_path = ""
        
        layout = QVBoxLayout(self)
        group = QGroupBox("匯入模式")
        v = QVBoxLayout()
        
        self.r1 = QRadioButton("僅鐵琴音軌 (保留現有馬達)")
        self.r2 = QRadioButton("僅馬達音軌 (保留現有鐵琴)")
        self.r4 = QRadioButton("智慧分軌 (依 MIDI 樂器)")
        self.r5 = QRadioButton("MidiBERT")
        self.r5.setStyleSheet("color: #a855f7; font-weight: bold;")
        self.r5.setChecked(True) 
        
        for r in [self.r1, self.r2, self.r4, self.r5]: 
            v.addWidget(r)
            
        group.setLayout(v)
        layout.addWidget(group)
        
        btn_layout = QHBoxLayout()
        self.btn_sel = QPushButton("選擇檔案")
        self.btn_sel.setStyleSheet("background-color: #3b82f6; font-weight: bold; padding: 8px;")
        self.btn_sel.clicked.connect(self.select_file)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_sel)
        layout.addLayout(btn_layout)
        
    def select_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "選擇 MIDI", "", "MIDI Files (*.mid *.midi)")
        if f:
            self.file_path = f
            if self.r1.isChecked(): self.mode = "glock_only"
            elif self.r2.isChecked(): self.mode = "motor_only"
            elif self.r4.isChecked(): self.mode = "unified_inst"
            elif self.r5.isChecked(): self.mode = "ai_midibert"
            self.accept()

class TutorialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新手教學")
        self.resize(500, 350)
        if parent: self.setStyleSheet(parent.styleSheet())
        
        self.steps = [
            {
                "title": "第一步：匯入歌曲",
                "desc": "點擊上方工具列的「匯入 MIDI」按鈕，選擇一首 MIDI 歌曲。\n\n建議選擇 MidiBERT 模式，或選擇使用已存歌曲。"
            },
            {
                "title": "第二步：連接硬體",
                "desc": "在工具列右側確認自動鐵琴機的 MAC 地址無誤後，點擊「連線 BLE」。\n\n如果連線成功，系統將準備好傳送音符指令給實體鐵琴機與馬達系統。"
            },
            {
                "title": "第三步：開始演奏",
                "desc": "一切準備就緒後，點擊左上角的「播放/暫停」按鈕，或按下空白鍵，即可開始自動演奏！\n\n右側會即時顯示琴鍵敲擊的視覺化動畫與馬達震動反饋。"
            }
        ]
        self.current_step = 0
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 40, 30, 30)
        
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff; margin-bottom: 10px;")
        layout.addWidget(self.lbl_title)
        
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("font-size: 15px; color: #d1d1d6; line-height: 1.5;")
        self.lbl_desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.lbl_desc, stretch=1)
        
        self.lbl_progress = QLabel()
        self.lbl_progress.setStyleSheet("font-size: 12px; color: #636366;")
        self.lbl_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_progress)
        
        btn_layout = QHBoxLayout()
        self.btn_prev = QPushButton("上一步")
        self.btn_prev.clicked.connect(self.prev_step)
        
        self.btn_next = QPushButton("下一步")
        self.btn_next.setStyleSheet("background-color: #0a84ff; color: white; font-weight: bold;")
        self.btn_next.clicked.connect(self.next_step)
        
        btn_layout.addWidget(self.btn_prev)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_next)
        
        layout.addLayout(btn_layout)
        
        self.update_ui()
        
    def prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_ui()
            
    def next_step(self):
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            self.update_ui()
        else:
            self.accept()
            
    def update_ui(self):
        step_data = self.steps[self.current_step]
        self.lbl_title.setText(step_data["title"])
        self.lbl_desc.setText(step_data["desc"])
        self.lbl_progress.setText(f"{self.current_step + 1} / {len(self.steps)}")
        
        self.btn_prev.setVisible(self.current_step > 0)
        if self.current_step == len(self.steps) - 1:
            self.btn_next.setText("開始使用")
        else:
            self.btn_next.setText("下一步")

MAC_DARK_QSS = """
QWidget { background-color: #121212; color: #e0e0e0; font-family: -apple-system, 'San Francisco', 'Helvetica Neue', 'Segoe UI', sans-serif; }
QLabel { color: #e0e0e0; font-size: 12px; }
*[bento="true"] { background-color: #1c1c1e; border-radius: 8px; border: 1px solid #2c2c2e; }
QPushButton { background-color: #2c2c2e; color: #ffffff; border-radius: 6px; padding: 6px 12px; border: 1px solid #3a3a3c; font-weight: 500; font-size: 12px; }
QPushButton:hover { background-color: #3a3a3c; border: 1px solid #48484a; }
QPushButton:pressed { background-color: #48484a; }
QPushButton:disabled { background-color: #1c1c1e; color: #636366; border: 1px solid #2c2c2e; }
QPushButton#playBtn { background-color: #1a3322; border: 1px solid #34c759; color: #34c759; }
QPushButton#playBtn:hover { background-color: #34c759; color: #ffffff; }
QPushButton#stopBtn { background-color: #331a1a; border: 1px solid #ff3b30; color: #ff3b30; }
QPushButton#stopBtn:hover { background-color: #ff3b30; color: #ffffff; }
QPushButton#exportBtn { background-color: #2a1b38; border: 1px solid #bf5af2; color: #bf5af2; }
QPushButton#exportBtn:hover { background-color: #bf5af2; color: #ffffff; }
QCheckBox { spacing: 6px; color: #e0e0e0; font-size: 12px; }
QCheckBox::indicator { width: 14px; height: 14px; border-radius: 4px; border: 1px solid #3a3a3c; background: #1c1c1e; }
QCheckBox::indicator:checked { background: #0a84ff; border: 1px solid #0a84ff; }
QComboBox, QLineEdit { background-color: #1c1c1e; border: 1px solid #3a3a3c; border-radius: 6px; padding: 4px 8px; color: #ffffff; font-size: 12px; }
QComboBox:hover, QLineEdit:hover { border: 1px solid #48484a; }
QSlider::groove:horizontal { border-radius: 2px; height: 4px; background: #3a3a3c; }
QSlider::handle:horizontal { background: #d1d1d6; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; border: 1px solid #1c1c1e; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QTextEdit { background-color: #000000; border: 1px solid #2c2c2e; border-radius: 8px; padding: 8px; font-family: monospace; color: #98989d; }
QSplitter::handle { background-color: #2c2c2e; height: 1px; }
"""

class AutoMusicView(QMainWindow):
    sig_play_clicked = pyqtSignal(bool)
    sig_stop_clicked = pyqtSignal()
    sig_import_midi_advanced = pyqtSignal(str, str) 
    sig_import_h = pyqtSignal(str)
    sig_export_h = pyqtSignal(str)
    sig_export_web = pyqtSignal(str)
    sig_save_song = pyqtSignal()
    sig_load_song = pyqtSignal(str)
    sig_manage_songs = pyqtSignal()
    sig_connect_ble = pyqtSignal(str)
    sig_disconnect_ble = pyqtSignal()
    sig_config_changed = pyqtSignal(dict)
    sig_sustain_changed = pyqtSignal(float)
    sig_undo = pyqtSignal()
    sig_copy = pyqtSignal(list)
    sig_paste = pyqtSignal()
    sig_delete = pyqtSignal(list)
    sig_note_added = pyqtSignal(int, int)
    sig_open_settings = pyqtSignal()
    sig_auto_transpose = pyqtSignal()
    sig_toggle_oob_mode = pyqtSignal()
    sig_close_app = pyqtSignal()
    
    sig_select_all = pyqtSignal()
    sig_quantize = pyqtSignal()
    sig_convert = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("自動鐵琴機")
        self.resize(1400, 900)
        self.setStyleSheet(MAC_DARK_QSS)
        self.setup_ui()

    def closeEvent(self, event):
        self.sig_close_app.emit()
        event.accept()

    def _create_bento(self, layout_cls=QVBoxLayout):
        box = QWidget()
        box.setProperty("bento", True)
        l = layout_cls(box)
        l.setContentsMargins(10, 5, 10, 5)
        return box, l

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        top_bar = QWidget()
        top_bar.setFixedHeight(180) 
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)

        left_panel, left_lyt = self._create_bento(QVBoxLayout)
        
        r1 = QHBoxLayout()
        self.btn_play = QPushButton("播放 / 暫停 (Space)"); self.btn_play.setObjectName("playBtn")
        self.btn_stop = QPushButton("停止"); self.btn_stop.setObjectName("stopBtn")
        
        self.combo_speed = QComboBox(); self.combo_speed.addItems(["0.5x", "1.0x", "1.5x", "2.0x"]); self.combo_speed.setCurrentText("1.0x")
        self.chk_mute_glock = QCheckBox("🔇 鐵琴靜音")
        self.chk_mute_motor = QCheckBox("🔇 馬達靜音")
        
        self.btn_import = QPushButton("匯入 MIDI")
        
        self.combo_library = QComboBox(); self.combo_library.addItem("--- 選擇已存歌曲 ---")
        self.btn_manage_songs = QPushButton("管理")
        self.btn_save_song = QPushButton("儲存")
        self.btn_export_web = QPushButton("匯出網頁"); self.btn_export_web.setObjectName("exportBtn")
        self.input_mac = QLineEdit("88:4A:EA:62:C8:87"); self.input_mac.setFixedWidth(130)
        self.btn_ble = QPushButton("連線 BLE")
        self.btn_disconnect = QPushButton("斷開")
        self.btn_settings = QPushButton("硬體設定")
        self.btn_tutorial = QPushButton("新手教學")
        self.btn_tutorial.setStyleSheet("background-color: #0a84ff; color: white; font-weight: bold;")
        self.btn_tutorial.clicked.connect(self.show_tutorial)
        
        for w in [self.btn_play, self.btn_stop, QLabel("速度:"), self.combo_speed, self.chk_mute_glock, self.chk_mute_motor, self.btn_import, self.combo_library, self.btn_manage_songs, self.btn_save_song, self.btn_export_web, self.input_mac, self.btn_ble, self.btn_disconnect, self.btn_settings, self.btn_tutorial]:
            r1.addWidget(w)
        r1.addStretch()
        left_lyt.addLayout(r1)



        r3 = QHBoxLayout()
        self.btn_auto_transpose = QPushButton("自動轉調")
        self.btn_auto_transpose.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold;")
        self.btn_oob_mode = QPushButton("🔄 超音域: 邊界吸附")
        self.btn_oob_mode.clicked.connect(self.sig_toggle_oob_mode.emit)
        
        self.slider_transpose = QSlider(Qt.Orientation.Horizontal); self.slider_transpose.setRange(-12, 12); self.slider_transpose.setValue(0); self.slider_transpose.setFixedWidth(80)
        self.lbl_transpose_val = QLabel("+0")
        self.slider_sustain = QSlider(Qt.Orientation.Horizontal); self.slider_sustain.setRange(1, 30); self.slider_sustain.setValue(10); self.slider_sustain.setFixedWidth(80)
        self.lbl_sustain_val = QLabel("1.0x")
        self.slider_arp_speed = QSlider(Qt.Orientation.Horizontal); self.slider_arp_speed.setRange(5, 50); self.slider_arp_speed.setValue(10); self.slider_arp_speed.setFixedWidth(80)
        self.lbl_arp_speed = QLabel("10ms")
        self.slider_gate_time = QSlider(Qt.Orientation.Horizontal); self.slider_gate_time.setRange(10, 100); self.slider_gate_time.setValue(100); self.slider_gate_time.setFixedWidth(80)
        self.lbl_gate_time = QLabel("100%")
        
        self.lbl_hit_rate = QLabel("命中率: 100%")
        self.combo_mode = QComboBox(); self.combo_mode.addItems(["混合分流", "純馬達"])
        self.chk_motors = [QCheckBox(f"M{i}") for i in range(4)]
        for c in self.chk_motors: c.setChecked(True)

        for w in [QLabel("移調:"), self.slider_transpose, self.lbl_transpose_val, self.btn_auto_transpose, self.btn_oob_mode,
                  self.lbl_hit_rate, self.combo_mode] + self.chk_motors:
            r3.addWidget(w)
        r3.addStretch()
        left_lyt.addLayout(r3)

        top_layout.addWidget(left_panel, stretch=3)

        right_panel, right_lyt = self._create_bento(QHBoxLayout)
        self.motor_widgets = {}
        for i in range(4):
            mw = SciFiMotorWidget(i)
            self.motor_widgets[i] = mw
            right_lyt.addWidget(mw)
        top_layout.addWidget(right_panel, stretch=1)

        main_layout.addWidget(top_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        
        midi_box, midi_lyt = self._create_bento(QVBoxLayout)
        midi_lyt.setContentsMargins(0, 0, 0, 0)
        
        lbl_glock = QLabel("  鐵琴音軌 (Solenoids) - [Ctrl+滾輪] 縮放, [Q] 量化對齊")
        lbl_glock.setStyleSheet("color: #e0e0e0; font-weight: 500; font-size: 13px; padding: 6px; border-bottom: 1px solid #2c2c2e;")
        
        self.piano_view_glock = PianoRollView(show_safe_zone=True)
        self.piano_view_glock.setStyleSheet("background-color: #121212; border: none; border-right: 1px solid #2c2c2e;")
        
        self.time_ruler = TimeRulerWidget(self.piano_view_glock)
        self.piano_view_glock.sig_zoom_changed.connect(lambda _: self.time_ruler.update())
        
        lbl_motor = QLabel("  馬達音軌 (Motors)")
        lbl_motor.setStyleSheet("color: #e0e0e0; font-weight: 500; font-size: 13px; padding: 6px; border-bottom: 1px solid #2c2c2e;")
        
        self.piano_view_motor = PianoRollView(show_safe_zone=False)
        self.piano_view_motor.setStyleSheet("background-color: #121212; border: none;")

        tracks_layout = QHBoxLayout()
        
        left_track_lyt = QVBoxLayout()
        left_track_lyt.setContentsMargins(0, 0, 0, 0)
        left_track_lyt.addWidget(lbl_glock)
        left_track_lyt.addWidget(self.time_ruler)
        left_track_lyt.addWidget(self.piano_view_glock, 1)
        
        right_track_lyt = QVBoxLayout()
        right_track_lyt.setContentsMargins(0, 0, 0, 0)
        right_track_lyt.addWidget(lbl_motor)
        # Note: we might want another time ruler for the right track, but for now we keep it simple
        right_track_lyt.addWidget(self.piano_view_motor, 1)
        
        tracks_layout.addLayout(left_track_lyt, 1)
        tracks_layout.addLayout(right_track_lyt, 1)
        
        midi_lyt.addLayout(tracks_layout, 1)

        self.piano_view_glock.horizontalScrollBar().valueChanged.connect(self.piano_view_motor.horizontalScrollBar().setValue)
        self.piano_view_motor.horizontalScrollBar().valueChanged.connect(self.piano_view_glock.horizontalScrollBar().setValue)
        self.piano_view_glock.sig_zoom_changed.connect(self.piano_view_motor.set_zoom)
        self.piano_view_motor.sig_zoom_changed.connect(self.piano_view_glock.set_zoom)

        self.piano_keyboard = PianoKeyboardWidget()
        midi_lyt.addWidget(self.piano_keyboard, 0)
        
        splitter.addWidget(midi_box)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        splitter.addWidget(self.console)
        
        splitter.setStretchFactor(0, 85)
        splitter.setStretchFactor(1, 15)
        
        main_layout.addWidget(splitter, 1)

        self.btn_play.clicked.connect(lambda: self.sig_play_clicked.emit(False))
        self.btn_stop.clicked.connect(self.sig_stop_clicked.emit)
        self.btn_import.clicked.connect(self._handle_btn_import_midi)
        self.btn_export_web.clicked.connect(self._handle_btn_export_web)
        self.btn_manage_songs.clicked.connect(self.sig_manage_songs.emit)
        self.btn_save_song.clicked.connect(self.sig_save_song.emit)
        self.combo_library.activated.connect(self._on_library_selected)
        self.btn_ble.clicked.connect(lambda: self.sig_connect_ble.emit(self.input_mac.text().strip()))
        self.btn_disconnect.clicked.connect(self.sig_disconnect_ble.emit)
        self.btn_settings.clicked.connect(self.sig_open_settings.emit)
        self.btn_auto_transpose.clicked.connect(self.sig_auto_transpose.emit)
        
        self.slider_transpose.valueChanged.connect(self._on_transpose_slider_changed)
        self.slider_sustain.valueChanged.connect(self._on_sustain_change)
        self.slider_arp_speed.valueChanged.connect(self._on_arp_speed_change)
        self.slider_gate_time.valueChanged.connect(self._on_gate_time_change)
        
        for c in self.chk_motors + [self.combo_mode]:
            if hasattr(c, 'stateChanged'): c.stateChanged.connect(self._emit_config)
            else: c.currentIndexChanged.connect(self._emit_config)
            
        self.piano_view_glock.note_added_sig.connect(self.sig_note_added.emit)
        self.piano_view_motor.note_added_sig.connect(self.sig_note_added.emit)
        
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(lambda: self.sig_play_clicked.emit(False))
        QShortcut(QKeySequence("Shift+Space"), self).activated.connect(lambda: self.sig_play_clicked.emit(True))
        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self.sig_undo.emit)
        QShortcut(QKeySequence.StandardKey.Copy, self).activated.connect(self._req_copy)
        QShortcut(QKeySequence.StandardKey.Paste, self).activated.connect(self.sig_paste.emit)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self).activated.connect(self._req_delete)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(self._req_delete)
        
        QShortcut(QKeySequence("Ctrl+A"), self).activated.connect(self.sig_select_all.emit)
        QShortcut(QKeySequence("Q"), self).activated.connect(self.sig_quantize.emit)

    def update_motor_dashboards(self, active_motors_data):
        for m_id, data in active_motors_data.items():
            if m_id in self.motor_widgets:
                if data is None: self.motor_widgets[m_id].set_state(0, 0, False)
                else: self.motor_widgets[m_id].set_state(data[0], data[1], data[2])

    def _handle_btn_import_midi(self):
        dialog = ImportMidiDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.file_path:
            self.sig_import_midi_advanced.emit(dialog.file_path, dialog.mode)
            
    def _handle_btn_export_web(self):
        # Open save file dialog
        f, _ = QFileDialog.getSaveFileName(self, "匯出網頁播放檔", "", "JSON Files (*.json)")
        if f:
            self.sig_export_web.emit(f)

    def sync_ui_from_config(self, config):
        self.combo_mode.setCurrentIndex(config.get('mode_idx', 0))
        for i, chk in enumerate(self.chk_motors): chk.setChecked(i in config.get('active_motors', []))
        t = config.get('transpose', 0)
        self.slider_transpose.blockSignals(True)
        self.slider_transpose.setValue(t)
        self.slider_transpose.blockSignals(False)
        self.lbl_transpose_val.setText(f"{t:+d}")
        
        arp = config.get('arp_speed_ms', 10)
        self.slider_arp_speed.blockSignals(True)
        self.slider_arp_speed.setValue(arp)
        self.slider_arp_speed.blockSignals(False)
        self.lbl_arp_speed.setText(f"{arp}ms")
        
        gt = config.get('gate_time', 100)
        self.slider_gate_time.blockSignals(True)
        self.slider_gate_time.setValue(gt)
        self.slider_gate_time.blockSignals(False)
        self.lbl_gate_time.setText(f"{gt}%")

        self.update_oob_btn_text(config.get('oob_mode', 'snap'))
        
    def update_oob_btn_text(self, mode):
        if mode == 'motor':
            self.btn_oob_mode.setText("🔄 超音域: 交給馬達")
            self.btn_oob_mode.setStyleSheet("background-color: #8b5cf6; color: white; font-weight: bold;")
        else:
            self.btn_oob_mode.setText("🔄 超音域: 邊界吸附")
            self.btn_oob_mode.setStyleSheet("")

    def _on_library_selected(self, index):
        if index > 0: self.sig_load_song.emit(self.combo_library.currentText())
    def update_library_list(self, song_names):
        self.combo_library.blockSignals(True)
        self.combo_library.clear(); self.combo_library.addItem("--- 選擇已存歌曲 ---"); self.combo_library.addItems(song_names)
        self.combo_library.blockSignals(False)

    def set_config_ui(self, cfg, sustain_mult):
        ui_elements = [self.combo_mode] + self.chk_motors + \
                      [self.slider_transpose, self.slider_sustain, self.slider_arp_speed, self.slider_gate_time]
        for c in ui_elements: c.blockSignals(True)
        self.combo_mode.setCurrentIndex(cfg.get('mode_idx', 0))
        active_motors = cfg.get('active_motors', [0,1,2,3])
        for i, chk in enumerate(self.chk_motors): chk.setChecked(i in active_motors)

        gate_val = cfg.get('gate_time', 100)
        self.slider_gate_time.setValue(gate_val); self.lbl_gate_time.setText(f"{gate_val} %")
        self.slider_transpose.setValue(cfg.get('transpose', 0)); self.lbl_transpose_val.setText(f"{cfg.get('transpose', 0):+} 半音")
        self.slider_sustain.setValue(int(sustain_mult * 10)); self.lbl_sustain_val.setText(f"{sustain_mult:.1f}x")
        arp_val = cfg.get('arp_speed_ms', 10)
        self.slider_arp_speed.setValue(arp_val); self.lbl_arp_speed.setText(f"{arp_val} ms")
        for c in ui_elements: c.blockSignals(False)
        self._emit_config()

    def _on_transpose_slider_changed(self, val): self.lbl_transpose_val.setText(f"{val:+}"); self._emit_config()
    def set_sustain_val(self, val):
        self.lbl_sustain_val.setText(f"{val:.1f}x")

    def show_tutorial(self):
        dlg = TutorialDialog(self)
        dlg.exec()

    def _on_sustain_change(self, val): mult = val / 10.0; self.lbl_sustain_val.setText(f"{mult:.1f}x"); self.sig_sustain_changed.emit(mult)
    def _on_arp_speed_change(self, val): self.lbl_arp_speed.setText(f"{val}ms"); self._emit_config()
    def _on_gate_time_change(self, val): self.lbl_gate_time.setText(f"{val}%"); self._emit_config()

    def _emit_config(self):
        cfg = {
            'mode_idx': self.combo_mode.currentIndex(), 'active_motors': [i for i, chk in enumerate(self.chk_motors) if chk.isChecked()],
            'transpose': self.slider_transpose.value(),
            'arp_speed_ms': self.slider_arp_speed.value(),
            'gate_time': self.slider_gate_time.value()
        }
        self.sig_config_changed.emit(cfg)

    def get_selected_notes(self):
        sel = [i.note_data for i in self.piano_view_glock.scene.selectedItems() if isinstance(i, NoteGraphicItem)]
        sel += [i.note_data for i in self.piano_view_motor.scene.selectedItems() if isinstance(i, NoteGraphicItem)]
        return sel

    def _req_copy(self):
        sel = self.get_selected_notes()
        if sel: self.sig_copy.emit(sel)

    def _req_delete(self):
        sel = self.get_selected_notes()
        if sel: self.sig_delete.emit(sel)

    def render_notes(self, glock_notes, motor_notes, on_change_cb, on_delete_cb):
        self.piano_view_glock.load_notes(glock_notes, on_change_cb, self.show_context_menu)
        self.piano_view_motor.load_notes(motor_notes, on_change_cb, self.show_context_menu)
        
        for view in [self.piano_view_glock, self.piano_view_motor]:
            for item in view.scene.items():
                if isinstance(item, NoteGraphicItem):
                    note = item.note_data
                    text_item = getattr(item, 'route_label', None)
                    if not text_item: 
                        text_item = QGraphicsTextItem(item)
                        item.route_label = text_item
                    
                    if getattr(note, 'is_ignored', False): 
                        text_item.setPlainText("Skip")
                        item.setBrush(QBrush(QColor("#334155")))
                    elif not getattr(note, 'is_motor', False): 
                        text_item.setPlainText(f"S{note.track_id}")
                        item.setBrush(QBrush(QColor(TRACK_COLORS[note.track_id % 15])))
                    else:
                        m_id = getattr(note, 'motor_id', 0)
                        chorus_m = getattr(note, 'chorus_motor_id', None)
                        text_item.setPlainText(f"M{m_id}+{chorus_m}" if chorus_m is not None else f"M{m_id}")
                        item.setBrush(QBrush(QColor(MOTOR_COLOR)))

    def show_context_menu(self, item, note_data):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; font-weight: bold; border-radius: 6px; }
            QMenu::item { padding: 8px 30px 8px 30px; border-radius: 4px; margin: 2px; }
            QMenu::item:selected { background-color: #3b82f6; }
            QMenu::separator { height: 1px; background: #475569; margin: 4px 10px; }
        """)
        
        action_convert = menu.addAction("轉換軌道 (鐵琴 ⟷ 馬達)\tCtrl+T")
        action_copy = menu.addAction("複製 (Copy)\tCtrl+C")
        menu.addSeparator() 
        action_delete = menu.addAction("刪除 (Delete)\tDel")
        
        targets = self.get_selected_notes()
        if not targets:
            targets = [note_data]
            
        action = menu.exec(QCursor.pos())
        
        if action == action_delete:
            self.sig_delete.emit(targets)
        elif action == action_convert:
            self.sig_convert.emit(targets)
        elif action == action_copy:
            self.sig_copy.emit(targets)

    def update_hit_rate(self, rate):
        self.lbl_hit_rate.setText(f"命中率: {rate:.1f}%")
        if rate > 80: self.lbl_hit_rate.setStyleSheet("color: #10b981;")
        elif rate > 50: self.lbl_hit_rate.setStyleSheet("color: #f59e0b;")
        else: self.lbl_hit_rate.setStyleSheet("color: #ef4444;")

    def set_ble_state(self, is_connected):
        if is_connected: self.btn_ble.setText("已連線"); self.btn_ble.setEnabled(False); self.input_mac.setEnabled(False); self.btn_disconnect.setEnabled(True)
        else: self.btn_ble.setText("連線 BLE"); self.btn_ble.setEnabled(True); self.input_mac.setEnabled(True); self.btn_disconnect.setEnabled(False)

    def update_console(self, msg, color="#94a3b8", time_str="--.--"):
        self.console.append(f"<span style='color:#475569;'>[{time_str}]</span> <span style='color:{color};'>{msg}</span>")
        sb = self.console.verticalScrollBar(); sb.setValue(sb.maximum())

    def update_playhead(self, time_us): 
        self.piano_view_glock.update_playhead(time_us)
        self.piano_view_motor.update_playhead(time_us)
        
    def play_keyboard_sound(self, pitch, is_motor, glock_synth, motor_synth): 
        if is_motor:
            motor_synth.play_note(pitch)
        else:
            glock_synth.play_note(pitch)
            
        self.piano_keyboard.press_key(pitch, is_motor)
        
    def show_message(self, title, msg, is_error=False):
        if is_error: QMessageBox.critical(self, title, msg)
        else: QMessageBox.information(self, title, msg)

    def open_hardware_dialog(self, physics, motor_profiler, ble_worker, serializer, config=None):
        dialog = HardwareSettingsDialog(physics, motor_profiler, config=config, test_fire_callback=None, test_motor_callback=None, parent=self)
        
        def cb_fire(tid):
            if ble_worker and getattr(ble_worker, 'is_running', False):
                ble_worker.send_packet(serializer.create_note_command(NoteData("t",60,0,0,False,tid)))
            else:
                QMessageBox.warning(dialog, "連線錯誤", "請先在主畫面點擊「連線 BLE」！\n(如果未連線，硬體是不會收到測試指令的喔)")
                
        def cb_motor(mid, rpm):
            if ble_worker and getattr(ble_worker, 'is_running', False):
                ble_worker.send_packet(serializer.create_motor_command(rpm, 1000, mid, 0))
            else:
                QMessageBox.warning(dialog, "連線錯誤", "請先在主畫面點擊「連線 BLE」！\n(如果未連線，硬體是不會收到測試指令的喔)")
                
        dialog.test_fire_callback = cb_fire
        dialog.test_motor_callback = cb_motor
        return dialog.exec()