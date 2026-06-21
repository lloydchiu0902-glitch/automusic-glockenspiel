/*
 * 自動鐵琴機韌體 (CNC Shield V3 + Arduino Mega)
 * - Active-Low 繼電器邏輯
 * - 9600bps 藍牙通訊
 * - 每次 Loop 最高解析 8 Bytes
 * - 60ms 電磁鐵敲擊脈衝
 */

#include <AccelStepper.h>

// ==========================================
// 1. 硬體腳位定義
// ==========================================
const int solenoidPins[15] = {22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50};
uint32_t solenoidTurnOffTime[15] = {0}; 

// 60毫秒敲擊脈衝
const uint32_t SOLENOID_PULSE_MS = 60;  

const int RELAY_PIN = 53;    // 繼電器控制腳位

const int EN_PIN = 8;        // CNC Shield 總開關
const int WAKEUP_PIN = 11;   // 強制喚醒 A4988

AccelStepper stepperX(AccelStepper::DRIVER, 2, 5); 
AccelStepper stepperY(AccelStepper::DRIVER, 3, 6); 
AccelStepper stepperZ(AccelStepper::DRIVER, 4, 7); 
AccelStepper stepperA(AccelStepper::DRIVER, 12, 13);
AccelStepper* steppers[4] = {&stepperX, &stepperY, &stepperZ, &stepperA};

// ==========================================
// 2. 通訊協定與環形緩衝區
// ==========================================
struct AutoMusicCommand {
  uint16_t seq_num;
  uint32_t timestamp_us;
  uint8_t cmd_type;
  uint8_t motor_id;
  uint32_t track_mask;
  uint16_t rpm;
  uint16_t accel;
};

const int BUFFER_SIZE = 300;
AutoMusicCommand cmdBuffer[BUFFER_SIZE];
int head = 0; 
int tail = 0; 
int cmdCount = 0; 

const byte HEADER_1 = 0xFE;
const byte HEADER_2 = 0xFE;
const int PACKET_SIZE = 16;
byte packetBuffer[PACKET_SIZE];
int packetIndex = 0;

uint32_t startTimeUs = 0;
bool isPlaying = false;
uint16_t expectedSeqNum = 0;

// 高密度穿插步進
inline void stepAll() {
  stepperX.runSpeed();
  stepperY.runSpeed();
  stepperZ.runSpeed();
  stepperA.runSpeed();
}

void setup() {
  Serial.begin(115200);  // 給電腦監控視窗看
  
  // 藍牙模組初始化為 9600bps
  Serial3.begin(9600);   

  Serial.println("\n=============================================");
  Serial.println(" 🚀 自動鐵琴機韌體");
  Serial.println("=============================================");

  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW); 

  pinMode(WAKEUP_PIN, OUTPUT);
  digitalWrite(WAKEUP_PIN, HIGH);

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // 預設關閉繼電器

  // 高電位觸發
  for (int i = 0; i < 15; i++) {
    pinMode(solenoidPins[i], OUTPUT);
    digitalWrite(solenoidPins[i], LOW); // LOW = 斷電不敲擊
  }

  for (int i = 0; i < 4; i++) {
    steppers[i]->setMaxSpeed(5000.0);
    steppers[i]->setAcceleration(2000.0);
  }

  Serial.println("✅ 系統已就緒，等待 Python 同步串流訊號...");
}

void loop() {
  stepAll();
  processSerialData();      
  stepAll(); 
  executeBufferedCommands();
  stepAll(); 
  updateSolenoids();
}

void processSerialData() {
  int bytesProcessed = 0; 
  
  // 限制單次迴圈解析量 < 8
  while (Serial3.available() > 0 && bytesProcessed < 8) {
    byte b = Serial3.read();
    packetBuffer[packetIndex++] = b;
    bytesProcessed++;

    if (packetIndex == 1 && packetBuffer[0] != HEADER_1) { packetIndex = 0; } 
    else if (packetIndex == 2 && packetBuffer[1] != HEADER_2) {
      if (packetBuffer[1] == HEADER_1) { packetBuffer[0] = HEADER_1; packetIndex = 1; } 
      else { packetIndex = 0; }
    } 
    else if (packetIndex >= PACKET_SIZE) {
      uint16_t receivedCrc = packetBuffer[14] | (packetBuffer[15] << 8);
      uint16_t calculatedCrc = calculateCRC16(packetBuffer, 14);
      
      if (calculatedCrc == receivedCrc) {
        byte cmdType = packetBuffer[2];
        
        if (cmdType == 0x04) {
            byte resp[7];
            resp[0] = 0xFE; resp[1] = 0xFE; resp[2] = 0x04;
            resp[3] = expectedSeqNum & 0xFF;
            resp[4] = (expectedSeqNum >> 8) & 0xFF;
            uint16_t rCrc = calculateCRC16(resp, 5);
            resp[5] = rCrc & 0xFF;
            resp[6] = (rCrc >> 8) & 0xFF;
            Serial3.write(resp, 7); 
        }
        else if (cmdType == 0x03) {
          uint16_t syncSeq = packetBuffer[4] | (packetBuffer[5] << 8);
          uint32_t syncTs; memcpy(&syncTs, &packetBuffer[6], 4);
          startTimeUs = micros() - syncTs;
          expectedSeqNum = syncSeq + 1;
          head = 0; tail = 0; cmdCount = 0;
          isPlaying = true;
          Serial.println("🔄 收到 SYNC 同步指令！開始播放！");
        } 
        else {
          uint16_t receivedSeq = packetBuffer[4] | (packetBuffer[5] << 8);
          uint32_t ts; memcpy(&ts, &packetBuffer[6], 4);
          int16_t diff = (int16_t)(receivedSeq - expectedSeqNum);
          
          if (ts == 0) {
             // 立即執行，不排入緩衝區
             if (cmdType != 0x05) {
                 // 若為手動敲擊或停止指令，清空目前預載的指令並暫停播放
                 head = 0; tail = 0; cmdCount = 0;
                 isPlaying = false; 
             } 
             
             if (diff >= 0) {
                 expectedSeqNum = receivedSeq + 1;
             }
             
             if (cmdType == 0x01) {
                uint32_t track_mask; memcpy(&track_mask, &packetBuffer[10], 4);
                fireSolenoids(track_mask);
             } else if (cmdType == 0x02) {
                uint16_t rpm; memcpy(&rpm, &packetBuffer[10], 2);
                byte motorId = packetBuffer[3];
                float stepsPerSec = rpm * 3.333333f;
                if (rpm > 0) {
                    if (stepsPerSec < 100.0f) stepsPerSec = 100.0f;
                    steppers[motorId]->setSpeed(stepsPerSec);
                } else {
                    steppers[motorId]->setSpeed(0);
                }
             }
             else if (cmdType == 0x05) {
                 byte relayState = packetBuffer[3];
                 digitalWrite(RELAY_PIN, relayState ? HIGH : LOW);
                 Serial.println(relayState ? "🔌 繼電器 ON" : "🔌 繼電器 OFF");
             }
          }
          else if (diff > 0) {
              // 發現掉包 (序列號跳號)，主動發送 0x04 狀態回報請求回填
              static uint32_t lastBackfillRequestMs = 0;
              if (millis() - lastBackfillRequestMs > 300) {
                  byte resp[7];
                  resp[0] = 0xFE; resp[1] = 0xFE; resp[2] = 0x04;
                  resp[3] = expectedSeqNum & 0xFF;
                  resp[4] = (expectedSeqNum >> 8) & 0xFF;
                  uint16_t rCrc = calculateCRC16(resp, 5);
                  resp[5] = rCrc & 0xFF;
                  resp[6] = (rCrc >> 8) & 0xFF;
                  Serial3.write(resp, 7); 
                  lastBackfillRequestMs = millis();
              }
              // 超前的封包直接丟棄，等待重傳 (解決重複播放)
          }
          else if (diff == 0) {
             // 順序正確的包
             expectedSeqNum = receivedSeq + 1; 
             byte motorId = packetBuffer[3];
             if (cmdCount < BUFFER_SIZE) {
               AutoMusicCommand cmd;
               cmd.seq_num = receivedSeq;
               cmd.timestamp_us = ts;
               cmd.cmd_type = cmdType;
               cmd.motor_id = motorId;
               if (cmdType == 0x01) {
                 memcpy(&cmd.track_mask, &packetBuffer[10], 4);
               } else if (cmdType == 0x02) {
                 memcpy(&cmd.rpm, &packetBuffer[10], 2);
                 memcpy(&cmd.accel, &packetBuffer[12], 2);
               }
               cmdBuffer[head] = cmd;
               head = (head + 1) % BUFFER_SIZE;
               cmdCount++;
             }
          }
          // diff < 0 的過期包(包含重傳產生的重複包)會自動被忽略，不做任何處理
        }
        packetIndex = 0; 
      } else {
        packetIndex = 0;
      }
    }
  }
}

void executeBufferedCommands() {
  while (cmdCount > 0) {
    uint32_t currentUs = micros() - startTimeUs;
    AutoMusicCommand cmd = cmdBuffer[tail];
    
    // timestamp_us == 0 代表測試指令，無條件放行
    bool isImmediateTest = (cmd.timestamp_us == 0);
    
    if (isImmediateTest || (isPlaying && currentUs >= cmd.timestamp_us)) {
      if (cmd.cmd_type == 0x01) {
        fireSolenoids(cmd.track_mask);
      } else if (cmd.cmd_type == 0x02) {
        float stepsPerSec = cmd.rpm * 3.333333f;
        if (cmd.rpm > 0) {
          if (stepsPerSec < 100.0f) stepsPerSec = 100.0f;
          steppers[cmd.motor_id]->setSpeed(stepsPerSec);
        } else {
          steppers[cmd.motor_id]->setSpeed(0); 
        }
      }
      
      tail = (tail + 1) % BUFFER_SIZE;
      cmdCount--;
    } else {
      break; 
    }
  }
}

void fireSolenoids(uint32_t trackMask) {
  for (int i = 0; i < 15; i++) {
    if (trackMask & (1UL << i)) {
      // 發射時給予 HIGH 觸發敲擊
      digitalWrite(solenoidPins[i], HIGH); 
      solenoidTurnOffTime[i] = millis() + SOLENOID_PULSE_MS; 
    }
  }
}

void updateSolenoids() {
  uint32_t currentMillis = millis();
  for (int i = 0; i < 15; i++) {
    if (solenoidTurnOffTime[i] > 0 && currentMillis >= solenoidTurnOffTime[i]) {
      // 到達時間後，自動恢復為 LOW (斷電)
      digitalWrite(solenoidPins[i], LOW); 
      solenoidTurnOffTime[i] = 0; 
    }
  }
}

uint16_t calculateCRC16(const uint8_t *data, uint8_t length) {
  uint16_t crc = 0x0000;
  for (uint8_t i = 0; i < length; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t j = 0; j < 8; j++) {
      if (crc & 0x8000) { crc = (crc << 1) ^ 0x1021; } 
      else { crc <<= 1; }
    }
  }
  return crc;
}