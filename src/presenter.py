import sys
import os
import json
from PyQt6.QtCore import QObject

from audio_synth import GlockenspielSynthesizer, MotorSynthesizer
from workers import BLEWorker, PlaybackWorker
from core_logic import NoteData, StepperMotorProfiler

class AutoMusicPresenter(QObject):
    def __init__(self, model, view):
        super().__init__()
        self.model = model
        self.view = view
        
        self.glock_synth = GlockenspielSynthesizer()
        self.motor_synth = MotorSynthesizer()
        
        self.ble_worker = None
        self.playback_worker = None
        self.motor_profiler = StepperMotorProfiler()
        
        self._connect_signals()
        self._init_data()

    def _connect_signals(self):
        v = self.view
        v.sig_play_clicked.connect(self.handle_play)
        v.sig_stop_clicked.connect(self.handle_stop)
        v.sig_connect_ble.connect(self.handle_connect_ble)
        v.sig_disconnect_ble.connect(self.handle_disconnect_ble)
        v.sig_config_changed.connect(self.handle_config_changed)
        v.sig_sustain_changed.connect(self.handle_sustain_changed)
        
        v.sig_import_midi_advanced.connect(self.handle_import_midi_advanced)
        v.sig_import_h.connect(self.handle_import_h)
        v.sig_export_h.connect(self.handle_export_h)
        
        v.sig_note_added.connect(self.handle_note_added)
        v.sig_undo.connect(self.handle_undo)
        v.sig_copy.connect(self.handle_copy)
        v.sig_paste.connect(self.handle_paste)
        v.sig_delete.connect(self.handle_delete)
        v.sig_save_song.connect(self.handle_save_song)
        v.sig_load_song.connect(self.handle_load_song)
        v.sig_export_web.connect(self.handle_export_web)
        v.sig_manage_songs.connect(self.handle_manage_songs)
        v.sig_open_settings.connect(self.handle_open_settings)
        v.sig_auto_transpose.connect(self.handle_auto_transpose)
        
        # Connect convert signal
        v.sig_convert.connect(self.handle_convert)
        
        v.piano_view_glock.notes_changed_cb = self.handle_notes_changed
        v.piano_view_motor.notes_changed_cb = self.handle_notes_changed
        v.piano_view_glock.note_deleted_sig = self.handle_single_delete
        v.piano_view_motor.note_deleted_sig = self.handle_single_delete

        v.piano_view_glock.sig_playhead_moved.connect(self.handle_playhead_moved)
        v.piano_view_motor.sig_playhead_moved.connect(self.handle_playhead_moved)
        v.piano_view_glock.sig_loop_region_changed.connect(self.handle_loop_region_changed)
        v.piano_view_motor.sig_loop_region_changed.connect(self.handle_loop_region_changed)

        v.sig_select_all.connect(v.piano_view_glock.select_all)
        v.sig_select_all.connect(v.piano_view_motor.select_all)
        v.sig_quantize.connect(self.handle_quantize)

    def _init_data(self):
        self.view.set_config_ui(self.model.config, self.model.sustain_multiplier)
        self.view.update_library_list(self.model.get_song_list())
        self._refresh_view()

    def _refresh_view(self):
        g_notes = [n for n in self.model.all_notes if not getattr(n, 'is_motor', False)]
        m_notes = [n for n in self.model.all_notes if getattr(n, 'is_motor', False)]
        self.view.render_notes(g_notes, m_notes, self.handle_notes_changed, self.handle_single_delete)
        self.view.update_hit_rate(self.model.hit_rate)

    def _log(self, msg, color="#94a3b8"):
        t = "0.00"
        if self.playback_worker and self.playback_worker.is_playing:
            t = f"{self.playback_worker.current_time_us / 1_000_000:.2f}"
        self.view.update_console(msg, color, t)

    def handle_connect_ble(self, mac):
        if self.ble_worker: self.ble_worker.stop()
        self.ble_worker = BLEWorker(mac)
        self.ble_worker.sig_log.connect(self._log)
        self.ble_worker.sig_connected.connect(self.view.set_ble_state)
        if self.playback_worker:
            self.ble_worker.sig_inquiry_response.connect(self.playback_worker.trigger_backfill)
        self.ble_worker.start()

    def handle_disconnect_ble(self):
        if self.ble_worker:
            self.ble_worker.stop()
            self.ble_worker = None
        self.view.set_ble_state(False)
        self._log("BLE disconnected.", "#f59e0b")

    def handle_playhead_moved(self, t_us):
        self.paused_time_us = t_us
        self.view.update_playhead(t_us)
        
    def handle_loop_region_changed(self, start_us, end_us):
        self.loop_region = (start_us, end_us)
        if hasattr(self, 'playback_worker') and self.playback_worker:
            self.playback_worker.loop_region = self.loop_region

    def handle_play(self, is_pause=False):
        if self.playback_worker and self.playback_worker.is_playing:
            if is_pause:
                self.paused_time_us = self.playback_worker.current_time_us
                self._log("Playback paused.", "#f59e0b")
            else:
                self.paused_time_us = getattr(self, 'play_start_time_us', 0)
                self.view.update_playhead(self.paused_time_us)
                self._log("Playback stopped.", "#f59e0b")
                
            self.playback_worker.stop()
            self.playback_worker = None
            return
            
        if not self.model.all_notes:
            self._log("Error: No notes available to play.", "#f59e0b")
            return
            
        start_time_us = getattr(self, 'paused_time_us', 0)
        self.play_start_time_us = start_time_us
        speed_str = self.view.combo_speed.currentText().replace("x", "")
        speed = float(speed_str) if speed_str else 1.0
        mute_glock = self.view.chk_mute_glock.isChecked()
        mute_motor = self.view.chk_mute_motor.isChecked()
        loop_region = getattr(self, 'loop_region', None)
            
        self.playback_worker = PlaybackWorker(self.model.all_notes, self.ble_worker, self.model.serializer, start_time_us, speed, mute_glock, mute_motor, loop_region)
        if self.ble_worker:
            try: self.ble_worker.sig_inquiry_response.disconnect()
            except: pass
            self.ble_worker.sig_inquiry_response.connect(self.playback_worker.trigger_backfill)
            
        self.playback_worker.sig_update_ui.connect(self.view.update_playhead)
        self.playback_worker.sig_play_note.connect(lambda p, m: self.view.play_keyboard_sound(p, m, self.glock_synth, self.motor_synth))
        self.playback_worker.sig_motor_state.connect(self._handle_motor_state) 
        self.playback_worker.sig_log.connect(self._log)
        self.playback_worker.sig_finished.connect(self.handle_finish)
        self.playback_worker.start()

    def _handle_motor_state(self, motor_id, hz, velocity):
        # Update frontend motor status
        if motor_id in self.view.motor_widgets:
            is_alert = (hz > 0 and (hz < 30 or hz > 500)) 
            self.view.motor_widgets[motor_id].set_state(hz, velocity, is_alert)

    def handle_finish(self):
        if self.playback_worker:
            self.playback_worker.stop()
            self.playback_worker = None
        self.paused_time_us = 0
        self.view.update_playhead(0)
        self.view.update_motor_dashboards({0: None, 1: None, 2: None, 3: None})

    def handle_stop(self):
        if self.playback_worker:
            self.playback_worker.stop()
            self.playback_worker = None
        self.paused_time_us = 0
        self.view.update_playhead(0)
        self.view.update_motor_dashboards({0: None, 1: None, 2: None, 3: None})

    def handle_config_changed(self, cfg):
        self.model.save_state()
        self.model.update_config(cfg)
        self._refresh_view()

    def handle_sustain_changed(self, mult):
        self.model.sustain_multiplier = mult
        if self.model.config.get('sustain_enable', True):
            self.model.re_route_all()
            self._refresh_view()

    def handle_import_midi_advanced(self, path, mode):
        self.model.save_state()
        success, err, _ = self.model.import_midi_advanced(path, mode)
        if success:
            self._log(f"MIDI imported: {path.split('/')[-1]}", "#569cd6")
            if getattr(self.model, 'detected_is_minor', False):
                self._log("AI Analysis: Detected minor key. Intelligent parallel modulation available.", "#a855f7")
            
            self.view.slider_transpose.setValue(0)
                
            self._refresh_view()
            self.view.update_playhead(0)
        else:
            self.view.show_message("匯入失敗", err, True)

    def handle_auto_transpose(self):
        best_offset = self.model.calculate_best_transpose(self.model.all_notes)
        current_offset = self.view.slider_transpose.value()
        
        if best_offset != current_offset:
            self._log(f"AI Auto-Transpose: 偵測到最佳移調為 {best_offset:+d} 半音，已自動套用以最大化白鍵打擊率。", "#10b981")
            self.view.slider_transpose.setValue(best_offset)
        else:
            self._log(f"AI Auto-Transpose: 目前設定 ({best_offset:+d}) 已經是最佳白鍵配置，無需移調。", "#10b981")

    def handle_import_h(self, path):
        self.model.save_state()
        success, err = self.model.import_arduino_h(path)
        if success:
            self._log(f"Arduino H file imported: {path.split('/')[-1]}", "#569cd6")
            self._refresh_view()
        else:
            self.view.show_message("匯入失敗", err, True)

    def handle_export_h(self, path):
        success, err = self.model.export_arduino(path)
        if success: self._log(f"Export successful: {path.split('/')[-1]}", "#10b981")
        else: self.view.show_message("匯出失敗", err, True)

    def handle_export_web(self, path):
        # Generate web JSON file
        self._log("Generating web playback file...", "#38bdf8")
        success, err = self.model.export_web_json(path)
        if success:
            self._log(f"Web file exported successfully: {path.split('/')[-1]}", "#10b981")
            self.view.show_message("匯出成功", f"檔案已儲存至:\n{path}\n\n您現在可以用手機網頁載入這個檔案來播放了！")
        else:
            self.view.show_message("匯出失敗", err, True)
            self._log(f"Export failed: {err}", "#ef4444")

    def handle_note_added(self, pitch, t_us):
        self.model.save_state()
        new_id = f"Manual_{len(self.model.all_notes)}"
        t_trig = max(0, t_us - self.model.physics.get_total_delay_us())
        n = NoteData(new_id, pitch, t_us, t_trig)
        n.base_duration_us = 200_000
        
        GLOCKENSPIEL_VALID_PITCHES = {79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96, 98, 100, 101, 103}
        n.is_motor = not (pitch in GLOCKENSPIEL_VALID_PITCHES)
            
        self.model.all_notes.append(n)
        self.model.re_route_all()
        self._refresh_view()

    # Implement track conversion logic
    def handle_convert(self, selected_notes):
        if not selected_notes: return
        self.model.save_state()
        
        for note in selected_notes:
            note.is_motor = not getattr(note, 'is_motor', False)
            
        self.model.re_route_all()
        self._refresh_view()
        self._log(f"Converted {len(selected_notes)} notes to alternate track.", "#38bdf8")

    def handle_notes_changed(self, changes):
        if not changes: return
        self.model.save_state()
        
        GLOCKENSPIEL_VALID_PITCHES = {79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96, 98, 100, 101, 103}
        
        for note, new_pitch, new_t_us in changes:
            note.pitch = new_pitch
            note.t_note_us = new_t_us
            note.t_trigger_us = max(0, new_t_us - self.model.physics.get_total_delay_us())
            
            if new_pitch in GLOCKENSPIEL_VALID_PITCHES:
                note.is_motor = False
            else:
                note.is_motor = True
                
        self.model.re_route_all()
        self._refresh_view()

    def handle_single_delete(self, graphic_item, note):
        self.model.save_state()
        if note in self.model.all_notes:
            self.model.all_notes.remove(note)
        self.model.re_route_all()
        self._refresh_view()

    def handle_delete(self, selected_notes):
        if not selected_notes: return
        self.model.save_state()
        self.model.all_notes = [n for n in self.model.all_notes if n not in selected_notes]
        self.model.re_route_all()
        self._refresh_view()
        self._log(f"Deleted {len(selected_notes)} notes.", "#ef4444")

    def handle_copy(self, selected_notes):
        if not selected_notes: return
        self.model.clipboard = [n.clone() for n in selected_notes]
        self._log(f"Copied {len(selected_notes)} notes.", "#38bdf8")

    def handle_paste(self):
        if not self.model.clipboard: return
        self.model.save_state()
        paste_offset_us = 500_000 
        new_notes = []
        for n in self.model.clipboard:
            nn = n.clone()
            nn.id = f"Pasted_{len(self.model.all_notes)}_{n.id}"
            nn.t_note_us += paste_offset_us
            nn.t_trigger_us += paste_offset_us
            new_notes.append(nn)
        self.model.all_notes.extend(new_notes)
        self.model.re_route_all()
        self._refresh_view()
        self._log(f"Pasted {len(new_notes)} notes.", "#38bdf8")

    def handle_undo(self):
        self.model.undo()
        self._refresh_view()
        self._log("Undo executed.", "#a855f7")

    def handle_quantize(self):
        self.model.save_state()
        grid_us = int(500_000 / 2) 
        for n in self.model.all_notes:
            quantized_time = round(n.t_note_us / grid_us) * grid_us
            n.t_note_us = quantized_time
            n.t_trigger_us = max(0, quantized_time - self.model.physics.get_total_delay_us())
        self.model.re_route_all()
        self._refresh_view()
        self._log("Quantization applied to all notes.", "#3b82f6")

    def handle_save_song(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self.view, "儲存歌曲", "請輸入歌曲名稱:", text=self.model.current_song_name)
        if ok and name:
            self.model.save_song(name)
            self.view.update_library_list(self.model.get_song_list())
            self._log(f"Song saved: {name}", "#10b981")

    def handle_load_song(self, name):
        if self.model.load_song(name):
            self.view.set_config_ui(self.model.config, self.model.sustain_multiplier)
            self._refresh_view()
            self._log(f"Song loaded: {name}", "#3b82f6")
            
    # File management operations (Rename/Delete)
    def handle_manage_songs(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QMessageBox, QInputDialog
        import json
        import os
        
        dialog = QDialog(self.view)
        dialog.setWindowTitle("管理已儲存歌曲")
        dialog.resize(350, 450)
        dialog.setStyleSheet("QDialog { background-color: #0f172a; color: white; } QPushButton { background-color: #3b82f6; color: white; border-radius: 4px; padding: 6px; font-weight: bold; } QPushButton:hover { background-color: #60a5fa; } QListWidget { background-color: #1e293b; color: white; border: 1px solid #475569; border-radius: 4px; padding: 5px; font-size: 14px; }")
        
        layout = QVBoxLayout(dialog)
        
        list_widget = QListWidget()
        list_widget.addItems(self.model.get_song_list())
        layout.addWidget(list_widget)
        
        btn_layout = QHBoxLayout()
        btn_rename = QPushButton("重新命名")
        btn_delete = QPushButton("刪除")
        btn_delete.setStyleSheet("background-color: #ef4444;")
        btn_layout.addWidget(btn_rename)
        btn_layout.addWidget(btn_delete)
        layout.addLayout(btn_layout)
        
        def get_library_path():
            # Check local and cwd paths for library
            path_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "song_library.json")
            path_cwd = os.path.join(os.getcwd(), "song_library.json")
            return path_cwd if os.path.exists(path_cwd) else path_dir

        def sync_model_memory(old_n, new_n=None):
            # Synchronize dictionaries across Model instances to maintain state consistency.
            for attr_name in dir(self.model):
                if not attr_name.startswith('__'):
                    attr = getattr(self.model, attr_name)
                    if isinstance(attr, dict) and old_n in attr:
                        if new_n:
                            attr[new_n] = attr.pop(old_n)
                        else:
                            del attr[old_n]

        def rename_song():
            item = list_widget.currentItem()
            if not item: return
            old_name = item.text()
            new_name, ok = QInputDialog.getText(dialog, "重新命名", "請輸入新名稱:", text=old_name)
            if ok and new_name and new_name != old_name:
                try:
                    path = get_library_path()
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if old_name in data:
                            data[new_name] = data.pop(old_name)
                            with open(path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                    else:
                        QMessageBox.warning(dialog, "警告", f"找不到實體存檔！(路徑: {path})")
                    
                    sync_model_memory(old_name, new_name)
                    list_widget.clear()
                    song_list = self.model.get_song_list()
                    list_widget.addItems(song_list)
                    self.view.update_library_list(song_list)
                    self._log(f"Song renamed: {old_name} -> {new_name}", "#10b981")
                except Exception as e:
                    QMessageBox.warning(dialog, "錯誤", f"重新命名失敗: {e}")
        
        def delete_song():
            item = list_widget.currentItem()
            if not item: return
            name = item.text()
            reply = QMessageBox.question(dialog, "確認刪除", f"確定要刪除歌曲「{name}」嗎？\n此動作無法復原！", 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    path = get_library_path()
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if name in data:
                            del data[name]
                            with open(path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                    else:
                        QMessageBox.warning(dialog, "警告", f"找不到實體存檔！(路徑: {path})")
                    
                    sync_model_memory(name)
                    list_widget.takeItem(list_widget.row(item))
                    self.view.update_library_list(self.model.get_song_list())
                    self._log(f"Song deleted: {name}", "#ef4444")
                except Exception as e:
                    QMessageBox.warning(dialog, "錯誤", f"刪除失敗: {e}")

        btn_rename.clicked.connect(rename_song)
        btn_delete.clicked.connect(delete_song)
        
        dialog.exec()
        
    def handle_open_settings(self):
        if self.view.open_hardware_dialog(self.model.physics, self.motor_profiler, self.ble_worker, self.model.serializer, self.model.config):
            self._log("Hardware parameters updated. Rerouting...", "#10b981")
            for note in self.model.all_notes: 
                note.t_trigger_us = max(0, note.t_note_us - self.model.physics.get_total_delay_us())
            self.model.re_route_all()
            self._refresh_view()