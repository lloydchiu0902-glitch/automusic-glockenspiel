from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QDoubleSpinBox, QSpinBox, QPushButton, QGroupBox, 
                             QFormLayout, QMessageBox, QTabWidget, QWidget, QGridLayout, QComboBox)
from PyQt6.QtCore import Qt

class HardwareSettingsDialog(QDialog):
    """硬體參數設定與電機測試控制台"""
    def __init__(self, physics, motor_profiler, config=None, test_fire_callback=None, test_motor_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("硬體設定與測試控制台")
        self.setModal(True)
        self.resize(700, 600)
        
        self.physics = physics
        self.motor_profiler = motor_profiler
        self.config = config if config is not None else {}
        self.routing_map = self.config.get('routing_map', {})
        self.test_fire_callback = test_fire_callback
        self.test_motor_callback = test_motor_callback
        
        self.init_ui()
        self.load_current_values()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.tab_params = QWidget()
        self.tab_ranges = QWidget()
        self.tab_routing = QWidget()
        self.tab_test = QWidget()
        
        self.tabs.addTab(self.tab_params, "參數設定")
        self.tabs.addTab(self.tab_ranges, "馬達音域責任區")
        self.tabs.addTab(self.tab_routing, "訊號路由標記")
        self.tabs.addTab(self.tab_test, "電機單獨測試")
        
        self._setup_params_tab()
        self._setup_ranges_tab()
        self._setup_routing_tab()
        self._setup_test_tab()
        
        layout.addWidget(self.tabs)
        
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("儲存並關閉")
        self.btn_save.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px;")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("padding: 8px 16px;")
        
        self.btn_save.clicked.connect(self.save_and_close)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _setup_params_tab(self):
        layout = QVBoxLayout(self.tab_params)
        
        group_physics = QGroupBox("鐵琴發射物理延遲設定")
        form_physics = QFormLayout()
        self.spin_comm = QDoubleSpinBox(); self.spin_comm.setRange(0, 500); self.spin_comm.setSuffix(" ms")
        self.spin_solenoid = QDoubleSpinBox(); self.spin_solenoid.setRange(0, 500); self.spin_solenoid.setSuffix(" ms")
        self.spin_height = QDoubleSpinBox(); self.spin_height.setRange(0.01, 1.0); self.spin_height.setSingleStep(0.01); self.spin_height.setSuffix(" m")
        form_physics.addRow("通訊延遲 (Comm):", self.spin_comm)
        form_physics.addRow("電磁鐵延遲 (Solenoid):", self.spin_solenoid)
        form_physics.addRow("落珠高度 (Drop Height):", self.spin_height)
        group_physics.setLayout(form_physics)
        layout.addWidget(group_physics)
        
        group_motor = QGroupBox("步進馬達共振避讓設定")
        form_motor = QFormLayout()
        self.spin_res_min = QSpinBox(); self.spin_res_min.setRange(0, 1000); self.spin_res_min.setSuffix(" RPM")
        self.spin_res_max = QSpinBox(); self.spin_res_max.setRange(0, 1000); self.spin_res_max.setSuffix(" RPM")
        self.spin_safe_accel = QSpinBox(); self.spin_safe_accel.setRange(1, 1000)
        self.spin_burst_accel = QSpinBox(); self.spin_burst_accel.setRange(1, 5000)
        form_motor.addRow("共振區間 下限:", self.spin_res_min)
        form_motor.addRow("共振區間 上限:", self.spin_res_max)
        form_motor.addRow("一般安全加速度:", self.spin_safe_accel)
        form_motor.addRow("避震爆發加速度:", self.spin_burst_accel)
        group_motor.setLayout(form_motor)
        layout.addWidget(group_motor)
        layout.addStretch()

    def _setup_ranges_tab(self):
        """Setup motor range configurations."""
        layout = QVBoxLayout(self.tab_ranges)
        group = QGroupBox("設定 1~4 號馬達負責的最低與最高音")
        grid = QGridLayout()
        
        desc = QLabel("設定每顆馬達專屬負責的最低與最高音。當遇到新音符時，系統會優先派發給「音域涵蓋該音符」的空閒馬達；若無完美匹配，則會啟動代打機制，交給最接近的空閒馬達。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; margin-bottom: 10px;")
        grid.addWidget(desc, 0, 0, 1, 4)
        
        self.range_combos = {}
        note_names = []
        for p in range(21, 109): # A0 to C8
            octave = (p // 12) - 1
            note_str = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][p % 12]
            note_names.append(f"{note_str}{octave} ({p})")
            
        for m in range(4):
            lbl = QLabel(f"馬達 M{m} 責任區:")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            c_min = QComboBox(); c_min.addItems(note_names)
            c_max = QComboBox(); c_max.addItems(note_names)
            
            grid.addWidget(lbl, m+1, 0)
            grid.addWidget(c_min, m+1, 1)
            grid.addWidget(QLabel("~"), m+1, 2)
            grid.addWidget(c_max, m+1, 3)
            
            self.range_combos[m] = (c_min, c_max)
            
        group.setLayout(grid)
        layout.addWidget(group)
        layout.addStretch()

    def _setup_routing_tab(self):
        layout = QVBoxLayout(self.tab_routing)
        group_routing = QGroupBox("MIDI 軌道訊號路由 (Track Routing)")
        v_route = QVBoxLayout()
        desc = QLabel("請標記各個 MIDI 軌道 (Track 0~15) 應對應的實體硬體。")
        desc.setStyleSheet("color: #666; margin-bottom: 15px;")
        v_route.addWidget(desc)
        
        grid = QGridLayout()
        self.route_combos = []
        options = ["電磁鐵 (Solenoid)", "步進馬達 0", "步進馬達 1", "步進馬達 2", "步進馬達 3"]
        
        for i in range(16):
            lbl = QLabel(f"軌道 {i}:")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            combo = QComboBox(); combo.addItems(options)
            self.route_combos.append(combo)
            row, col = divmod(i, 4)
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(combo, row, col * 2 + 1)
            
        v_route.addLayout(grid)
        group_routing.setLayout(v_route)
        layout.addWidget(group_routing)
        layout.addStretch()

    def _setup_test_tab(self):
        layout = QVBoxLayout(self.tab_test)
        group_solenoid = QGroupBox("電磁鐵單軌測試 (15 軌)")
        grid = QGridLayout()
        for i in range(15):
            btn = QPushButton(f"軌道 {i}")
            btn.setStyleSheet("QPushButton { background-color: #3b82f6; color: white; border-radius: 4px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #2563eb; }")
            btn.clicked.connect(lambda checked, track_id=i: self._fire_test(track_id))
            row, col = divmod(i, 5)
            grid.addWidget(btn, row, col)
        group_solenoid.setLayout(grid)
        layout.addWidget(group_solenoid)
        
        group_motor = QGroupBox("步進馬達發聲測試 (4 顆)")
        v_motor = QVBoxLayout()
        self.notes_map = {
            "自訂輸入": None, "C3 (131Hz)": 39, "D3 (147Hz)": 44, "E3 (165Hz)": 49,
            "F3 (175Hz)": 52, "G3 (196Hz)": 59, "A3 (220Hz)": 66, "B3 (247Hz)": 74, 
            "C4 (262Hz)": 79, "D4 (294Hz)": 88, "E4 (330Hz)": 99, "F4 (349Hz)": 105, 
            "G4 (392Hz)": 118, "A4 (440Hz)": 132, "B4 (494Hz)": 148, "C5 (523Hz)": 157
        }
        self.motor_spins = []
        for m in range(4):
            h_row = QHBoxLayout()
            lbl = QLabel(f"馬達 {m}:"); lbl.setFixedWidth(40)
            combo = QComboBox(); combo.addItems(self.notes_map.keys())
            spin = QSpinBox(); spin.setRange(0, 3000); spin.setSuffix(" RPM"); spin.setValue(79)
            self.motor_spins.append(spin)
            combo.currentTextChanged.connect(lambda text, s=spin: s.setValue(self.notes_map[text]) if self.notes_map.get(text) is not None else None)
            
            btn_test = QPushButton("發出聲音")
            btn_test.setStyleSheet("background-color: #8b5cf6; color: white; font-weight: bold; border-radius: 4px; padding: 6px;")
            btn_test.clicked.connect(lambda checked, motor_id=m: self._motor_test(motor_id, self.motor_spins[motor_id].value()))
            
            btn_stop = QPushButton("停止")
            btn_stop.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; border-radius: 4px; padding: 6px;")
            btn_stop.clicked.connect(lambda checked, motor_id=m: self._motor_test(motor_id, 0))
            
            for w in [lbl, combo, spin, btn_test, btn_stop]: h_row.addWidget(w)
            v_motor.addLayout(h_row)
            
        group_motor.setLayout(v_motor)
        layout.addWidget(group_motor)
        layout.addStretch()

    def _fire_test(self, track_id):
        if self.test_fire_callback: self.test_fire_callback(track_id)
    def _motor_test(self, motor_id, rpm):
        if self.test_motor_callback: self.test_motor_callback(motor_id, rpm)

    def load_current_values(self):
        self.spin_comm.setValue(self.physics.t_comm_us / 1000.0)
        self.spin_solenoid.setValue(self.physics.t_solenoid_us / 1000.0)
        self.spin_height.setValue(self.physics.h_meters)
        
        res_min, res_max = self.motor_profiler.resonance_band
        self.spin_res_min.setValue(res_min)
        self.spin_res_max.setValue(res_max)
        self.spin_safe_accel.setValue(self.motor_profiler.safe_accel)
        self.spin_burst_accel.setValue(self.motor_profiler.burst_accel)
        
        for m in range(4):
            rmin, rmax = self.config.get('motor_ranges', {}).get(m, (36 + m*12, 47 + m*12))
            self.range_combos[m][0].setCurrentIndex(max(0, rmin - 21))
            self.range_combos[m][1].setCurrentIndex(max(0, rmax - 21))

        for i in range(16):
            val = self.routing_map.get(str(i), self.routing_map.get(i, "solenoid"))
            if val == "solenoid": self.route_combos[i].setCurrentIndex(0)
            elif str(val).startswith("motor_"):
                try: self.route_combos[i].setCurrentIndex(int(str(val).split("_")[1]) + 1)
                except: self.route_combos[i].setCurrentIndex(0)

    def save_and_close(self):
        if self.spin_res_min.value() >= self.spin_res_max.value():
            QMessageBox.warning(self, "參數錯誤", "共振區間的上限必須大於下限！")
            return
            
        self.physics.update_params(comm_ms=self.spin_comm.value(), solenoid_ms=self.spin_solenoid.value(), height_m=self.spin_height.value())
        self.motor_profiler.update_params(res_min=self.spin_res_min.value(), res_max=self.spin_res_max.value(), safe_accel=self.spin_safe_accel.value(), burst_accel=self.spin_burst_accel.value())
        
        ranges = {}
        for m in range(4):
            rmin = self.range_combos[m][0].currentIndex() + 21
            rmax = self.range_combos[m][1].currentIndex() + 21
            if rmin > rmax: rmin, rmax = rmax, rmin 
            ranges[m] = (rmin, rmax)
        self.config['motor_ranges'] = ranges
        
        for i in range(16):
            idx = self.route_combos[i].currentIndex()
            self.routing_map[i] = "solenoid" if idx == 0 else f"motor_{idx-1}"
        self.config['routing_map'] = self.routing_map
        
        self.accept()