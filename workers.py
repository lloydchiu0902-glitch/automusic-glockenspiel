import time
import asyncio
import struct
from PyQt6.QtCore import QThread, pyqtSignal

try:
    from bleak import BleakClient
    HAS_BLEAK = True
except ImportError:
    HAS_BLEAK = False

def calc_crc16(data) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc

class BLEWorker(QThread):
    sig_log = pyqtSignal(str, str) 
    sig_connected = pyqtSignal(bool)
    sig_inquiry_response = pyqtSignal(int) 

    def __init__(self, mac_address):
        super().__init__()
        self.mac_address = mac_address
        self.char_uuid = None
        self.packet_queue = asyncio.Queue()
        self.is_running = True

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.async_ble_task())

    async def async_ble_task(self):
        self.sig_log.emit(f"Connecting to {self.mac_address}...", "#d4d4d4")
        if not HAS_BLEAK:
            self.sig_log.emit("Error: bleak package not found. Run pip install bleak", "#ef4444")
            self.sig_connected.emit(False)
            return

        try:
            async with BleakClient(self.mac_address, timeout=10.0) as client:
                target_char = None
                can_write_without_response = False
                known_uart_uuids = ["0000ffe1-0000-1000-8000-00805f9b34fb", "0000ffe2-0000-1000-8000-00805f9b34fb"]
                
                for service in client.services:
                    for char in service.characteristics:
                        if char.uuid.lower() in known_uart_uuids:
                            target_char = char
                            can_write_without_response = "write-without-response" in char.properties
                            break
                    if target_char: break
                        
                if not target_char:
                    for service in client.services:
                        if service.uuid.startswith("000018"): continue
                        for char in service.characteristics:
                            if "write-without-response" in char.properties:
                                target_char = char
                                can_write_without_response = True
                                break
                            elif "write" in char.properties:
                                target_char = char
                                break
                        if target_char: break
                            
                if not target_char:
                    self.sig_log.emit("Error: Bluetooth UART channel not found.", "#ef4444")
                    self.sig_connected.emit(False)
                    return
                    
                self.char_uuid = target_char.uuid
                
                def notification_handler(sender, data):
                    if len(data) >= 7 and data[0] == 0xFE and data[1] == 0xFE and data[2] == 0x04:
                        crc_received = struct.unpack_from('<H', data, 5)[0]
                        crc_calc = calc_crc16(data[:5])
                        if crc_received == crc_calc:
                            expected_seq = struct.unpack_from('<H', data, 3)[0]
                            self.sig_inquiry_response.emit(expected_seq)

                if "notify" in target_char.properties or "indicate" in target_char.properties:
                    await client.start_notify(self.char_uuid, notification_handler)

                self.sig_connected.emit(True)
                self.sig_log.emit(f"BLE Connected. TX Channel: {self.char_uuid[:8].upper()}", "#10b981")
                
                while self.is_running:
                    packet = await self.packet_queue.get()
                    if not self.is_running: break
                    if packet:
                        try:
                            await client.write_gatt_char(self.char_uuid, packet, response=not can_write_without_response)
                        except Exception as e:
                            print(f"BLE TX Error: {e}")
                    await asyncio.sleep(0.015) 
                    
        except Exception as e:
            if self.is_running:
                self.sig_log.emit(f"BLE connection failed or interrupted: {str(e)}", "#ef4444")
                self.sig_connected.emit(False)

    def send_packet(self, packet: bytes):
        if hasattr(self, 'loop') and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.packet_queue.put(packet), self.loop)

    def stop(self):
        self.is_running = False
        if hasattr(self, 'loop') and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.packet_queue.put(b''), self.loop)

class PlaybackWorker(QThread):
    sig_update_ui = pyqtSignal(int)
    sig_play_note = pyqtSignal(int, bool)
    # Send synchronous signal to frontend with Motor_ID, Hz, Velocity
    sig_motor_state = pyqtSignal(int, float, int) 
    sig_log = pyqtSignal(str, str)
    sig_finished = pyqtSignal()
    
    def __init__(self, all_notes, ble_worker, serializer, start_time_us=0, speed=1.0, mute_glock=False, mute_motor=False, loop_region=None):
        super().__init__()
        self.all_notes = all_notes
        self.ble_worker = ble_worker
        self.serializer = serializer
        self.is_playing = False
        self.start_time_us = start_time_us
        self.speed = speed
        self.mute_glock = mute_glock
        self.mute_motor = mute_motor
        self.loop_region = loop_region

    def trigger_backfill(self, expected_seq):
        current_seq = self.serializer.seq_num
        diff = (current_seq - expected_seq) % 65536
        self.sig_log.emit(f"Arduino requested backfill for sequence: {expected_seq}", "#3b82f6")
        if 0 < diff < 3000:
            for i in range(diff):
                seq = (expected_seq + i) % 65536
                if seq in self.serializer.history:
                    packet = self.serializer.history[seq]
                    if self.ble_worker:
                        self.ble_worker.send_packet(packet)
            self.sig_log.emit(f"Successfully backfilled {diff} dropped packets.", "#10b981")
        else:
            self.sig_log.emit("No missing packets or gap too large. Resuming stream.", "#d7ba7d")

    def run(self):
        self.is_playing = True
        self.current_time_us = self.start_time_us
        
        for n in self.all_notes:
            if n.t_note_us + getattr(n, 'duration_us', 200_000) <= self.current_time_us:
                n.triggered = True
                n.finished = True
                n.sent = True
            else:
                n.triggered = False
                n.finished = False 
                n.sent = False 
            
        if self.ble_worker:
            self.ble_worker.send_packet(self.serializer.create_sync_command(self.start_time_us))
            self.sig_log.emit("Sending SYNC signal. Sequence reset, starting stream...", "#10b981")
            
        last_tick = time.perf_counter()
        pending_motor_stops = [] 
        
        PREBUFFER_TIME = 2_500_000
        while self.is_playing:
            now = time.perf_counter()
            self.current_time_us += int((now - last_tick) * 1_000_000 * self.speed)
            last_tick = now
            
            if self.loop_region and self.loop_region[1] > self.loop_region[0]:
                if self.current_time_us >= self.loop_region[1]:
                    self.current_time_us = self.loop_region[0]
                    # Reset states for notes that need to be replayed
                    for n in self.all_notes:
                        if n.t_note_us + getattr(n, 'duration_us', 200_000) > self.current_time_us:
                            n.triggered = False
                            n.finished = False
                            if n.t_trigger_us >= self.current_time_us:
                                n.sent = False

            PREBUFFER_TIME = 2_500_000 

            stops_to_remove = []
            for stop_event in pending_motor_stops:
                stop_time_us, motor_id = stop_event
                if (self.current_time_us + PREBUFFER_TIME) >= stop_time_us:
                    if self.ble_worker:
                        self.ble_worker.send_packet(self.serializer.create_motor_command(0, 2000, motor_id, stop_time_us))
                    stops_to_remove.append(stop_event)
                    
            for s in stops_to_remove:
                pending_motor_stops.remove(s)

            for note in self.all_notes:
                if getattr(note, 'is_ignored', False): continue
                    
                is_motor = getattr(note, 'is_motor', False)
                is_muted = (self.mute_glock and not is_motor) or (self.mute_motor and is_motor)

                if not getattr(note, 'sent', False) and (self.current_time_us + PREBUFFER_TIME) >= note.t_trigger_us:
                    note.sent = True
                    if self.ble_worker and not is_muted:
                        if not is_motor:
                            self.ble_worker.send_packet(self.serializer.create_note_command(note))
                        else:
                            rpm = int((440.0 * (2.0 ** ((note.effective_pitch - 69) / 12.0))) * 0.3)
                            motor_id = getattr(note, 'motor_id', 0)
                            accel = getattr(note, 'accel_val', 2000)
                            self.ble_worker.send_packet(self.serializer.create_motor_command(rpm, accel, motor_id, note.t_trigger_us))
                            pending_motor_stops.append((note.t_trigger_us + note.duration_us, motor_id))
                
                # Trigger: Update motor icon state
                if not getattr(note, 'triggered', False) and self.current_time_us >= note.t_note_us:
                    note.triggered = True
                    if not is_muted:
                        self.sig_play_note.emit(note.effective_pitch, is_motor)
                        if is_motor:
                            hz = 440.0 * (2.0 ** ((note.effective_pitch - 69) / 12.0))
                            self.sig_motor_state.emit(getattr(note, 'motor_id', 0), hz, note.velocity)


                # Release: Reset motor icon state
                if getattr(note, 'triggered', False) and not getattr(note, 'finished', False) and self.current_time_us >= note.t_note_us + getattr(note, 'duration_us', 200_000):
                    note.finished = True
                    if getattr(note, 'is_motor', False) and not is_muted:
                        self.sig_motor_state.emit(getattr(note, 'motor_id', 0), 0.0, 0)


            time.sleep(0.001)
            
            if self.current_time_us % 16000 < 2000:
                self.sig_update_ui.emit(self.current_time_us)

            if self.all_notes and self.current_time_us > self.all_notes[-1].t_note_us + 1_000_000:
                if not pending_motor_stops:
                    self.is_playing = False
                    self.sig_log.emit("Playback finished.", "#4ec9b0")
                    self.sig_finished.emit()

    def stop(self):
        self.is_playing = False
        if self.ble_worker:
            for m in range(4): self.ble_worker.send_packet(self.serializer.create_motor_command(0, 1000, m, 0))