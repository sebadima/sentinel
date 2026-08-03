#include <esp_system.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <HTTPUpdate.h>
#include <ArduinoJson.h>
#include "time.h"
#include <esp_sntp.h>
#include "RTClib.h"
#include "Adafruit_FRAM_I2C.h"
#include <esp_task_wdt.h>
#include <SPI.h>
#include <Adafruit_MAX31865.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <LiquidCrystal_I2C.h>

const int FW_VERSION = 876;
#define VERSION_ADDR 10
#define CURRENT_FW_VERSION 1
#define DEBUG_MODE 1

#define RTC_MODE_ADDR 11
#define RTC_MODE_UTC 0xAA  

#ifdef __cplusplus
extern "C" {
#endif
uint8_t temprature_sens_read();
#ifdef __cplusplus
}
#endif

#define ADS_ADDR 0x48
#define WDT_TIMEOUT 30

// --- SPI PIN PER MAX31865 (PT1000 HARDWARE) ---
#define SPI_MISO 25
#define SPI_MOSI 26
#define SPI_SCK  27
#define SPI_CS   32

#define ONE_WIRE_BUS_33 33

OneWire oneWire33(ONE_WIRE_BUS_33);
DallasTemperature sensors33(&oneWire33);
LiquidCrystal_I2C lcd(0x27, 16, 2);

Adafruit_MAX31865 thermo = Adafruit_MAX31865(SPI_CS, &SPI);

#define FRAM_WRITE_PTR_LOC 0
#define FRAM_READ_PTR_LOC 2
#define FRAM_DATA_START 4
#define FRAM_SIZE 32768

#include "secrets.h"
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* serverUrl = SERVER_URL;
const char* updateUrl = UPDATE_URL;
const char* ntpServer = NTP_SERVER;

const char* TZ_INFO = "CET-1CEST,M3.5.0,M10.5.0/3";

struct SystemCheckpoints {
  volatile uint32_t last_loop_tick;
  volatile uint32_t last_i2c_read;
  volatile uint32_t last_net_sync;
  volatile bool ota_in_progress;
};

SystemCheckpoints checkpoints;

#define TIMEOUT_LOOP_TICK  10000
#define TIMEOUT_I2C_READ   45000
#define TIMEOUT_NET_SYNC  180000

struct Payload {
  char timestamp[28];
  float voltage_0;
  float voltage_1;
  float voltage_2;
  float voltage_3;
  float dht_temp;
  float dht_hum;
  uint32_t timestamp_utc;
  float ads_ch0;
  float ads_ch1;
  float ads_ch2;
  float ads_ch3;
  uint16_t checksum;
};

struct Record {
  uint32_t magic = 0xDEADBEEF;
  uint16_t version = CURRENT_FW_VERSION;
  Payload data;
};

RTC_DS3231 rtc;
Adafruit_FRAM_I2C fram;
uint16_t framWriteAddr = FRAM_DATA_START;
uint16_t framReadAddr = FRAM_DATA_START;
unsigned long lastMillis = 0;
unsigned long lastSyncMillis = 0;
const long interval = 15000;
const long syncInterval = 30000;
unsigned long lastWiFiRetryMillis = 0;
const unsigned long wifiRetryInterval = 30000;

const unsigned long FORCED_SYNC_INTERVAL = 604800000UL;

int lastDriftSeconds = 0;
bool rtcUtcModeValidated = false;

void vSupervisorTask(void *pvParameters) {
  esp_task_wdt_add(xTaskGetCurrentTaskHandle());

  while (1) {
    if (checkpoints.ota_in_progress) {
      esp_task_wdt_reset();
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }

    uint32_t now = millis();
    bool system_healthy = true;

    if (now - checkpoints.last_loop_tick > TIMEOUT_LOOP_TICK) {
      Serial.println("[WDT][CRITICAL] Loop principale in starvation!");
      system_healthy = false;
    }

    if (now - checkpoints.last_i2c_read > TIMEOUT_I2C_READ) {
      Serial.println("[WDT][CRITICAL] Sottosistema I2C/Sensori bloccato!");
      system_healthy = false;
    }

    if (now - checkpoints.last_net_sync > TIMEOUT_NET_SYNC) {
      Serial.println("[WDT][CRITICAL] Stack di rete / HTTP Client appeso!");
      system_healthy = false;
    }

    if (system_healthy) {
      esp_task_wdt_reset();
    } else {
      Serial.println("[WDT][FATAL] Condizione di guasto rilevata. Forzatura crash hardware...");
    }

    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

bool checkOneWire() {
  Serial.println("[POST][1WIRE] Verifica bus 1-Wire...");
  pinMode(ONE_WIRE_BUS_33, INPUT);
  delay(10);

  bool bus33_fail = (digitalRead(ONE_WIRE_BUS_33) == LOW);
  if (bus33_fail) Serial.println("[POST][1WIRE][FATAL] Bus 33 in CORTO a GND o Pull-up assente!");

  if (!bus33_fail) sensors33.begin();
  delay(50);

  int count33 = bus33_fail ? 0 : sensors33.getDeviceCount();
  Serial.printf("[POST][1WIRE] Bus PIN 33 → Sensori: %d\n", count33);

  if (count33 == 0) {
    Serial.println("[POST][1WIRE][WARN] Ramo 33 morto o vuoto.");
  }
  return true;
}

bool checkMAX31865() {
  Serial.println("[POST][PT100] Verifica MAX31865...");

  lcd.setCursor(0, 1);
  lcd.print("PT100 CHECK...    ");
  delay(100);

  // FIX: Allineamento a 2WIRE per bypassare i jumper fisici tagliati
  thermo.begin(MAX31865_2WIRE);
  delay(50);

  uint8_t err = thermo.readFault();
  
  if (err) {
    Serial.printf("[POST][PT100][WARN] Errore MAX31865: 0x%02X\n", err);
    lcd.setCursor(0, 1);
    lcd.print("PT100 ERR         ");
    delay(1000);
    return false;
  }

  // FIX MATEMATICO: Allineamento ai valori reali della scheda PT1000 rilevati al banco
  float temp = thermo.temperature(1000.0, 4300.0);
  Serial.printf("[POST][PT100] Temperatura rilevata: %.2f C\n", temp);

  if (temp < -50 || temp > 200) {
    Serial.println("[POST][PT100][WARN] Temperatura fuori range operativo");
    lcd.setCursor(0, 1);
    lcd.print("PT100 OUT RANGE   ");
    delay(1000);
    return false;
  }

  Serial.println("[POST][PT100] MAX31865 OK");
  lcd.setCursor(0, 1);
  lcd.print("PT100 OK          ");
  delay(700);
  return true;
}

bool checkFRAM() {
  Serial.println("[POST][FRAM] Verifica fisica e logica FRAM...");
  Wire.beginTransmission(0x50);
  if (Wire.endTransmission() != 0) {
    Serial.println("[POST][FRAM][FATAL] Nessun ACK. FRAM fisicamente assente o bus I2C morto.");
    return false;
  }

  uint8_t test_pattern = 0xAA;
  uint8_t read_val = 0x00;

  Wire.beginTransmission(0x50);
  Wire.write(0x00);
  Wire.write(0x00);
  Wire.write(test_pattern);
  if (Wire.endTransmission() != 0) {
    Serial.println("[POST][FRAM][FATAL] Errore in scrittura pattern I2C.");
    return false;
  }

  Wire.beginTransmission(0x50);
  Wire.write(0x00);
  Wire.write(0x00);
  Wire.endTransmission();

  Wire.requestFrom(0x50, 1);
  if (Wire.available()) {
    read_val = Wire.read();
  }

  if (read_val == test_pattern) {
    Serial.println("[POST][FRAM] Pattern test HW passato (0xAA). OK.");
    return true;
  } else {
    Serial.println("[POST][FRAM][FATAL] Pattern test fallito. Hardware corrotto o assente.");
    return false;
  }
}

#define DS3231_I2C_ADDR 0x68
#define DS3231_REG_STATUS 0x0F
#define DS3231_OSF_BIT 0x80

bool checkDS3231() {
  Serial.println("[POST][RTC] Inizio verifica DS3231...");

  lcd.setCursor(0, 1);
  lcd.print("RTC CHECK...      ");
  delay(100);

  bool deviceFound = false;
  bool oscillatorValid = true;
  uint8_t statusReg = 0;
  uint8_t lastError = 0;

  for (int i = 0; i < 5; i++) {
    Wire.beginTransmission(DS3231_I2C_ADDR);
    lastError = Wire.endTransmission();
    if (lastError == 0) {
      deviceFound = true;
      break;
    }
    delay(50);
  }

  if (!deviceFound) {
    Serial.printf("[POST][RTC][ERR] DS3231 non trovato (ultimo err=%u)\n", lastError);
    lcd.setCursor(0, 1);
    lcd.print("RTC MISSING       ");
    delay(1000);
    return false;
  }

  bool statusReadOK = false;
  for (int attempt = 0; attempt < 3; attempt++) {
    Wire.beginTransmission(DS3231_I2C_ADDR);
    Wire.write(DS3231_REG_STATUS);
    uint8_t err = Wire.endTransmission(false);
    if (err == 0) {
      uint8_t received = Wire.requestFrom((uint8_t)DS3231_I2C_ADDR, (uint8_t)1);
      if (received == 1 && Wire.available()) {
        statusReg = Wire.read();
        statusReadOK = true;
        break;
      }
    }
    delay(20);
  }

  if (!statusReadOK || statusReg == 0xFF) {
    lcd.setCursor(0, 1);
    lcd.print("RTC COMM ERR      ");
    delay(1000);
    return false;
  }

  if (statusReg & DS3231_OSF_BIT) {
    oscillatorValid = false;
    Serial.println("[POST][RTC][WARN] OSF attivo - oscillatore fermato in passato");
  }

  if (oscillatorValid) {
    lcd.setCursor(0, 1);
    lcd.print("RTC OK            ");
    delay(700);
    return true;
  }

  lcd.setCursor(0, 1);
  lcd.print("RTC BATT LOW      ");
  delay(1500);
  return true;
}

bool checkI2C(int sdaPin, int sclPin) {
  pinMode(sdaPin, INPUT_PULLUP);
  pinMode(sclPin, INPUT_PULLUP);
  delay(10);

  if (digitalRead(sdaPin) == HIGH) return true;

  pinMode(sclPin, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(sclPin, LOW);
    delayMicroseconds(5);
    digitalWrite(sclPin, HIGH);
    delayMicroseconds(5);
    pinMode(sdaPin, INPUT_PULLUP);
    if (digitalRead(sdaPin) == HIGH) return true;
  }
  return false;
}

bool checkKernelCore() {
  esp_reset_reason_t reason = esp_reset_reason();
  if (reason == ESP_RST_BROWNOUT || reason == ESP_RST_PANIC || reason == ESP_RST_INT_WDT || reason == ESP_RST_TASK_WDT) {
    return false;
  }
  if (ESP.getFreeHeap() < 100000) return false;
  return true;
}

uint16_t calculateChecksum(Payload p) {
  p.checksum = 0;
  uint16_t sum1 = 0;
  uint16_t sum2 = 0;
  const uint8_t* data = (const uint8_t*)&p;
  for (size_t i = 0; i < sizeof(Payload); ++i) {
    sum1 = (sum1 + data[i]) % 255;
    sum2 = (sum2 + sum1) % 255;
  }
  return (sum2 << 8) | sum1;
}

void checkMemoryConsistency() {
  uint8_t storedVersion = fram.read(VERSION_ADDR);
  if (storedVersion != CURRENT_FW_VERSION) {
    uint16_t start = FRAM_DATA_START;
    fram.write(FRAM_WRITE_PTR_LOC, (uint8_t*)&start, 2);
    fram.write(FRAM_READ_PTR_LOC, (uint8_t*)&start, 2);
    fram.write(VERSION_ADDR, CURRENT_FW_VERSION);
  }
  
  uint8_t rtcMode = fram.read(RTC_MODE_ADDR);
  if (rtcMode != RTC_MODE_UTC) {
    fram.write(RTC_MODE_ADDR, RTC_MODE_UTC);
    rtcUtcModeValidated = false;  
  } else {
    rtcUtcModeValidated = true;
  }
}

bool readFromFram(uint16_t address, Payload& p) {
  Record r;
  memset(&r, 0, sizeof(Record));
  fram.read(address, (uint8_t*)&r, sizeof(Record));

  if (r.magic != 0xDEADBEEF || r.data.checksum != calculateChecksum(r.data)) return false;

  r.data.timestamp[sizeof(r.data.timestamp)-1] = '\0';
  p = r.data;
  return true;
}

void saveToFram(Payload p) {
  Record r;
  r.data = p;
  r.data.checksum = calculateChecksum(r.data);

  if (framWriteAddr + sizeof(Record) > FRAM_SIZE) framWriteAddr = FRAM_DATA_START;
  uint16_t nextWriteAddr = framWriteAddr + sizeof(Record);
  if (nextWriteAddr > FRAM_SIZE) nextWriteAddr = FRAM_DATA_START;

  if (nextWriteAddr == framReadAddr) {
    framReadAddr += sizeof(Record);
    if (framReadAddr + sizeof(Record) > FRAM_SIZE) framReadAddr = FRAM_DATA_START;
    fram.write(FRAM_READ_PTR_LOC, (uint8_t*)&framReadAddr, 2);
  }

  fram.write(framWriteAddr, (uint8_t*)&r, sizeof(Record));
  framWriteAddr = nextWriteAddr;
  fram.write(FRAM_WRITE_PTR_LOC, (uint8_t*)&framWriteAddr, 2);
}

float readADC(uint16_t config) {
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(0x01);
  Wire.write((uint8_t)(config >> 8));
  Wire.write((uint8_t)(config & 0xFF));
  if (Wire.endTransmission() != 0) return -1.0;
  delay(20);
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(0x00);
  Wire.endTransmission();
  Wire.requestFrom(ADS_ADDR, 2);
  if (Wire.available() == 2) {
    int16_t raw = (Wire.read() << 8) | Wire.read();
    return (float)raw * (4.096 / 32768.0);
  }
  return -1.0;
}

void syncTime(bool force = false) {
  if (WiFi.status() != WL_CONNECTED) return;
  
  Wire.beginTransmission(0x68);
  Wire.write(0x0F);
  if (Wire.endTransmission() != 0) return;
  Wire.requestFrom(0x68, 1);
  byte status = Wire.read();
  bool oscillatorStopped = (status & 0b10000000);
  
  static unsigned long lastPeriodicSync = 0;
  bool needPeriodicSync = (millis() - lastPeriodicSync >= FORCED_SYNC_INTERVAL);
  bool needSync = force || oscillatorStopped || needPeriodicSync || !rtcUtcModeValidated;
  
  if (!needSync) return;
  if (needPeriodicSync) lastPeriodicSync = millis();
  
  configTzTime(TZ_INFO, ntpServer);
  int retry = 0;
  while (sntp_get_sync_status() == SNTP_SYNC_STATUS_RESET && ++retry < 50) {
    vTaskDelay(pdMS_TO_TICKS(100));
  }

  if (sntp_get_sync_status() != SNTP_SYNC_STATUS_COMPLETED) {
    if (needPeriodicSync) lastPeriodicSync = 0;
    return;
  }
  
  time_t ntpTimeUTC;
  time(&ntpTimeUTC);
  if (ntpTimeUTC < 1704067200) return;

  rtc.adjust(DateTime(ntpTimeUTC));
  Wire.beginTransmission(0x68);
  Wire.write(0x0F);
  Wire.write(status & 0b01111111);
  Wire.endTransmission();
  
  rtcUtcModeValidated = true;
  fram.write(RTC_MODE_ADDR, RTC_MODE_UTC);
}

void triggerOTA() {
  if (WiFi.status() != WL_CONNECTED) return;
  WiFiClient client;
  HTTPClient http;
  http.begin(client, updateUrl);
  int httpCode = http.GET();
  if (httpCode == 200) {
    StaticJsonDocument<256> doc;
    deserializeJson(doc, http.getString());
    int remoteVersion = doc["version"];
    String downloadUrl = doc["url"];
    if (remoteVersion > FW_VERSION) {
      checkpoints.ota_in_progress = true;
      httpUpdate.rebootOnUpdate(true);
      t_httpUpdate_return ret = httpUpdate.update(client, downloadUrl);
      if (ret == HTTP_UPDATE_FAILED) checkpoints.ota_in_progress = false;
    }
  }
  http.end();
}

int sendToFlask(Payload p, int rtcStatus, int drift) {
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.begin(client, serverUrl);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["version"]   = FW_VERSION;
  doc["status"]    = rtcStatus;
  doc["drift"]     = drift;
  doc["timestamp"] = p.timestamp;
  doc["timestamp_utc"] = p.timestamp_utc;
  doc["voltage_0"] = p.voltage_0;
  doc["voltage_1"] = p.voltage_1;
  doc["voltage_2"] = p.voltage_2;
  doc["voltage_3"] = p.voltage_3;
  doc["dht_temp"]  = p.dht_temp;
  doc["dht_hum"]   = p.dht_hum;
  doc["rtc_temp"]  = (float)((temprature_sens_read() - 32) / 1.8);
  doc["ads_ch0"]   = p.ads_ch0;
  doc["ads_ch1"]   = p.ads_ch1;
  doc["ads_ch2"]   = p.ads_ch2;
  doc["ads_ch3"]   = p.ads_ch3;

  String json;
  serializeJson(doc, json);
  int code = http.POST(json);
  http.end();
  return code;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.printf("\n\n[BOOT] --- FW V%d INIT ---\n", FW_VERSION);
  Wire.begin(21, 22);
  
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SPI_CS);
  
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("INIT SYSTEM V3.x");
  lcd.setCursor(0, 1);
  lcd.print("LAUNCHING POST..");
  delay(800);

  const char* subsys[] = {
    "KERNEL CORE",
    "I2C RECOVERY",
    "DS3231 RTC",
    "FRAM SECTOR",
    "MAX31865 PT100",
    "1-WIRE BUS"
  };

  bool statusResults[6];
  statusResults[0] = checkKernelCore();
  statusResults[1] = checkI2C(21, 22);
  statusResults[2] = checkDS3231();
  statusResults[3] = checkFRAM();
  statusResults[4] = checkMAX31865();
  statusResults[5] = checkOneWire();

  for (int i = 0; i < 6; i++) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("POST CHECK:");
    lcd.setCursor(0, 1);
    lcd.print(subsys[i]);
    delay(500);

    if (statusResults[i]) {
      lcd.setCursor(12, 1);
      lcd.print("[OK]");
    } else {
      lcd.setCursor(9, 1);
      lcd.print("[FAULT]");
      if (i == 0) while(1);
    }
    delay(500);
  }

  lcd.clear();
  sensors33.begin();
  sensors33.setWaitForConversion(false);

  if (!rtc.begin()) while(1);
  if (!fram.begin(0x50)) while(1);

  #ifdef DEBUG_MODE
    framWriteAddr = FRAM_DATA_START;
    framReadAddr = FRAM_DATA_START;
    fram.write(FRAM_WRITE_PTR_LOC, (uint8_t*)&framWriteAddr, 2);
    fram.write(FRAM_READ_PTR_LOC, (uint8_t*)&framReadAddr, 2);
    fram.write(VERSION_ADDR, CURRENT_FW_VERSION);
  #else
    checkMemoryConsistency();
    framWriteAddr = FRAM_DATA_START;
    for (uint16_t i = FRAM_DATA_START; i <= FRAM_SIZE - sizeof(Record); i += sizeof(Record)) {
      uint32_t magic;
      fram.read(i, (uint8_t*)&magic, 4);
      if (magic == 0xDEADBEEF) framWriteAddr = i + sizeof(Record);
    }
    fram.write(FRAM_WRITE_PTR_LOC, (uint8_t*)&framWriteAddr, 2);
    fram.read(FRAM_READ_PTR_LOC, (uint8_t*)&framReadAddr, 2);
  #endif

  if (framWriteAddr < FRAM_DATA_START || framWriteAddr >= FRAM_SIZE) framWriteAddr = FRAM_DATA_START;
  if (framReadAddr < FRAM_DATA_START || framReadAddr >= FRAM_SIZE) framReadAddr = FRAM_DATA_START;

  uint32_t boot_time = millis();
  checkpoints.last_loop_tick = boot_time;
  checkpoints.last_i2c_read = boot_time;
  checkpoints.last_net_sync = boot_time;
  checkpoints.ota_in_progress = false;

  esp_task_wdt_init(WDT_TIMEOUT, true);

  setenv("TZ", TZ_INFO, 1);
  tzset();
  configTzTime(TZ_INFO, ntpServer);

  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    triggerOTA();
    syncTime(); 
  }

  xTaskCreatePinnedToCore(vSupervisorTask, "WDT_Supervisor", 3072, NULL, 1, NULL, 0);
  Serial.println("[BOOT] --- SYSTEM READY ---\n");
}

void loop() {
  checkpoints.last_loop_tick = millis();

  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWiFiRetryMillis >= wifiRetryInterval) {
      lastWiFiRetryMillis = millis();
      WiFi.disconnect();
      WiFi.begin(ssid, password);
    }
  }

  if (millis() - lastSyncMillis >= syncInterval) {
    lastSyncMillis = millis();
    syncTime();
    triggerOTA();
  }

  if (millis() - lastMillis >= interval) {
    lastMillis = millis();
    DateTime now = rtc.now();
    Payload current;
    memset(&current, 0, sizeof(Payload));
    
    time_t rtcTime = now.unixtime(); 
    struct tm timeinfo;
    localtime_r(&rtcTime, &timeinfo);
    
    int year = timeinfo.tm_year + 1900;
    int currentStatus = 0;

    if (year < 2024 || year > 2035) {
        rtcUtcModeValidated = false; 
        currentStatus |= 0x08; 
        snprintf(current.timestamp, sizeof(current.timestamp), "1970-01-01T00:00:00+00:00");
    } else {
        int offsetHours = (timeinfo.tm_isdst > 0) ? 2 : 1;
        char tzSign = '+';
        snprintf(current.timestamp, sizeof(current.timestamp), 
                 "%04d-%02d-%02dT%02d:%02d:%02d%c%02d:00",
                 year, timeinfo.tm_mon + 1, timeinfo.tm_mday,
                 timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec,
                 tzSign, offsetHours);
    }
    
    current.timestamp_utc = rtcTime;

    // --- SEZIONE PT1000 FIX HARDWARE ---
    thermo.clearFault(); 
    // FIX MATEMATICO: Sonda PT1000 (1000.0) e Resistenza di Riferimento a 4300.0 Ohm
    float pt100_temp = thermo.temperature(1000.0, 4300.0);
    
    if (pt100_temp < -50 || pt100_temp > 200) {
      uint8_t fault = thermo.readFault();
      Serial.printf("[REG_ERR] Fault MAX31865 attivo: 0x%02X\n", fault);
      currentStatus |= 0x04;
      current.voltage_0 = -99.0;
    } else {
      current.voltage_0 = pt100_temp; // Salva la temperatura reale pulita
    }

    sensors33.requestTemperatures();
    float t_raw_33 = sensors33.getTempCByIndex(0);

    if (t_raw_33 == DEVICE_DISCONNECTED_C || t_raw_33 == 85.00 || t_raw_33 < -55.0) {
      currentStatus |= 0x04;
      current.voltage_1 = -99.0;
    } else {
      current.voltage_1 = t_raw_33;
    }

    current.ads_ch0 = readADC(0xC3E3);
    current.ads_ch1 = readADC(0xD3E3);
    current.ads_ch2 = readADC(0xE3E3); 
    current.ads_ch3 = readADC(0xF3E3);

    // FIX HARDWARE: Scatta il flag 0x04 SOLO se readADC restituisce -1.0 (mancata risposta I2C)
    if (current.ads_ch0 < -0.9f || current.ads_ch1 < -0.9f || current.ads_ch2 < -0.9f || current.ads_ch3 < -0.9f) {
        currentStatus |= 0x04;
    }

    current.dht_temp = 0.0;
    current.dht_hum = 0.0;

    checkpoints.last_i2c_read = millis();

    if (lastDriftSeconds == -1 || lastDriftSeconds > 10) {
      currentStatus |= 0x01;
    }

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("PT:");
    if (current.voltage_0 == -99.0) {
      lcd.print("ERR ");
    } else {
      lcd.print(current.voltage_0, 1);
      lcd.print("C ");
    }

    lcd.print("T2:");
    if (current.voltage_1 == -99.0) {
      lcd.print("ERR ");
    } else {
      lcd.print(current.voltage_1, 1);
      lcd.print("C");
    }

    lcd.setCursor(0, 1);
    if (WiFi.status() == WL_CONNECTED) {
      lcd.print("WIFI:OK RSSI:");
      lcd.print(WiFi.RSSI());
    } else {
      lcd.print("WIFI:NO RSSI:---");
    }

    bool currentSent = false;
    if (WiFi.status() == WL_CONNECTED) {
      while (framReadAddr != framWriteAddr) {
        if (framReadAddr + sizeof(Record) > FRAM_SIZE) framReadAddr = FRAM_DATA_START;

        Payload old;
        if (readFromFram(framReadAddr, old)) {
          int code = sendToFlask(old, 0, 0);
          if (code == 201) {
            framReadAddr += sizeof(Record);
            if (framReadAddr + sizeof(Record) > FRAM_SIZE) framReadAddr = FRAM_DATA_START;
            fram.write(FRAM_READ_PTR_LOC, (uint8_t*)&framReadAddr, 2);
          } else {
            break;
          }
        } else {
          framReadAddr += sizeof(Record);
          if (framReadAddr + sizeof(Record) > FRAM_SIZE) framReadAddr = FRAM_DATA_START;
          fram.write(FRAM_READ_PTR_LOC, (uint8_t*)&framReadAddr, 2);
        }
        yield();
      }

      if (sendToFlask(current, currentStatus, lastDriftSeconds) == 201) {
        currentSent = true;
      }
      checkpoints.last_net_sync = millis();
    }

    if (!currentSent) {
      saveToFram(current);
    }
  }
}
