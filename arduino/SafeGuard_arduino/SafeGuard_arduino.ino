// Safe Guard: Arduino Uno node
// Follows the system sheet, scenarios S1 to S8 and conditions U1 to U18.
// Friend's logic is kept where it still applies: RFID access card, the "area is safe"
// screen, and the pin layout (MQ-2 on A1, RFID on pins 7 and 9).
//
//   Uno -> PC:  READY   BASELINE,<n>   MOTION,1   GAS,1   GAS,0   LEVEL,<n>
//               GRANTED,<UID>   DENIED,<UID>
//   PC  -> Uno: BUZZER,ON   BUZZER,OFF
//
// What changed, and why:
//   - Gas thresholds are calibrated at start-up: the average clean-air reading plus a
//     margin. A normal reading on your sensor can no longer look like a leak, and the
//     fixed 900/800 values are gone.
//   - The gas alarm clears when the reading stays below its off level for 3 seconds.
//     Before, it had to fall below 800, so a slow sensor could keep the warning on.
//   - The status LED is now driven. It was never wired in the code before.
//   - The buzzer and LED turn on for an intruder the PC confirms (BUZZER,ON).
//   - The RFID reader is checked every loop and the 2-second messages no longer block,
//     so PC commands are never missed.
//   - The motion message no longer waits behind the gas screen.

#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN  7
#define RST_PIN 9

byte authorizedUID[] = {0x12, 0x5A, 0x61, 0x1A};
MFRC522 rfid(SS_PIN, RST_PIN);
LiquidCrystal_I2C lcd(0x27, 16, 2);

const int PIR_PIN   = 2;    // HC-SR501 OUT
const int GAS_PIN   = A1;   // MQ-2 analog output
const int ALARM_PIN = 5;    // transistor base -> buzzer (pin 7 is the RFID SS pin)
const int LED_PIN   = 4;    // status LED

const unsigned long PIR_WARMUP_MS       = 20000;  // U2: PIR ignored before this
const unsigned long GAS_WARMUP_MS       = 20000;  // U1/U7: gas calibration ends here
const unsigned long MOTION_COOLDOWN_MS  = 3000UL;   // U4
const unsigned long MOTION_FLASH_MS     = 5000UL;   // U3: "Motion detected" on the LCD
const unsigned long RFID_MSG_MS         = 2000UL;   // how long access messages stay
const unsigned long IGNORE_AFTER_CARD_MS = 10000UL; // motion ignored after a granted card
const unsigned long GAS_CLEAR_HOLD_MS   = 3000UL;   // U10: reading must stay low this long
const unsigned long LEVEL_EVERY_MS      = 1000UL;   // LEVEL,<n> interval
const unsigned long LCD_EVERY_MS        = 250UL;

const int GAS_RISE = 200;   // alarm when the reading is baseline + 200
const int GAS_FALL = 100;   // clears when the reading is below baseline + 100 for 3 s

int gasValue = 0;
int gasBaseline = 0;
int gasOnLevel = 0;
int gasOffLevel = 0;
unsigned long calSum = 0;
unsigned long calCount = 0;
bool calibrated = false;
bool readySent = false;
unsigned long gasClearSince = 0;     // 0 = not counting
unsigned long lastLevelSent = 0;

bool gasAlert = false;               // U8 to U10
bool intrusionOn = false;            // U11 to U13, set by the PC
bool motionLast = false;
unsigned long lastMotionSent = 0;
unsigned long motionFlashUntil = 0;
unsigned long ignoreMotionUntil = 0;
unsigned long grantedFlashUntil = 0;
unsigned long deniedFlashUntil = 0;
unsigned long lastLcd = 0;
String rxLine = "";

void setup()
{
  pinMode(PIR_PIN, INPUT);
  pinMode(GAS_PIN, INPUT);
  pinMode(ALARM_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(ALARM_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(9600);
  lcd.init();
  lcd.backlight();
  showRows("Safe Guard", "Starting...");
  SPI.begin();
  rfid.PCD_Init();
}

void loop()
{
  unsigned long now = millis();

  readPcCommands();
  checkRFID();

  bool motionNow = (digitalRead(PIR_PIN) == HIGH);
  checkGas(now);
  reportMotion(motionNow, now);
  checkReady();

  bool alarm = gasAlert || intrusionOn;
  digitalWrite(ALARM_PIN, alarm ? HIGH : LOW);
  digitalWrite(LED_PIN, alarm ? HIGH : LOW);

  if (now - lastLcd >= LCD_EVERY_MS) {
    lastLcd = now;
    updateLcd(now);
  }
}

// ---------- gas: calibration, alarm with hold-off, and level reports ----------
void checkGas(unsigned long now)
{
  gasValue = analogRead(GAS_PIN);

  if (!calibrated) {
    // average the clean-air readings between the PIR warm-up and the end of warm-up
    if (now >= PIR_WARMUP_MS) {
      calSum += gasValue;
      calCount++;
    }
    if (now >= GAS_WARMUP_MS) {
      gasBaseline = (calCount > 0) ? (int)(calSum / calCount) : gasValue;
      gasOnLevel  = gasBaseline + GAS_RISE;
      gasOffLevel = gasBaseline + GAS_FALL;
      calibrated = true;
      Serial.print("BASELINE,");
      Serial.println(gasBaseline);
    }
  } else if (!gasAlert) {
    if (gasValue > gasOnLevel) {
      gasAlert = true;
      gasClearSince = 0;
      Serial.println("GAS,1");                 // sent once per event
    }
  } else {
    if (gasValue < gasOffLevel) {
      if (gasClearSince == 0) {
        gasClearSince = now;
      }
      if (now - gasClearSince >= GAS_CLEAR_HOLD_MS) {
        gasAlert = false;
        gasClearSince = 0;
        Serial.println("GAS,0");
      }
    } else {
      gasClearSince = 0;                       // still high: restart the hold timer
    }
  }

  if (now - lastLevelSent >= LEVEL_EVERY_MS) {
    lastLevelSent = now;
    Serial.print("LEVEL,");
    Serial.println(gasValue);
  }
}

void checkReady()
{
  if (calibrated && !readySent) {
    readySent = true;
    Serial.println("READY");
  }
}

// ---------- PIR: one MOTION,1 per movement, after warm-up ----------
void reportMotion(bool motionNow, unsigned long now)
{
  bool rising = motionNow && !motionLast;
  motionLast = motionNow;

  if (!rising) return;
  if (now < PIR_WARMUP_MS) return;                        // U2
  if (now < ignoreMotionUntil) return;                    // a card was granted
  if (now - lastMotionSent < MOTION_COOLDOWN_MS) return;  // U4

  Serial.println("MOTION,1");
  lastMotionSent = now;
  motionFlashUntil = now + MOTION_FLASH_MS;               // U3: LCD shows Motion
}

// ---------- commands from the PC ----------
void readPcCommands()
{
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      handlePcLine(rxLine);
      rxLine = "";
    } else if (c != '\r' && rxLine.length() < 32) {
      rxLine += c;
    }
  }
}

void handlePcLine(String line)
{
  line.trim();
  if (line == "BUZZER,ON") {
    intrusionOn = true;
  } else if (line == "BUZZER,OFF") {
    intrusionOn = false;                  // gas can still keep the buzzer on
  }
  // anything else is ignored (U14)
}

// ---------- RFID: friend's access logic, without blocking delays ----------
void checkRFID()
{
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;

  boolean match = true;
  for (byte i = 0; i < 4; i++) {
    if (rfid.uid.uidByte[i] != authorizedUID[i]) {
      match = false;
      break;
    }
  }

  String uid = uidString();
  unsigned long now = millis();
  if (match) {
    Serial.print("GRANTED,");
    Serial.println(uid);
    intrusionOn = false;                                 // card silences the intruder alarm
    ignoreMotionUntil = now + IGNORE_AFTER_CARD_MS;
    grantedFlashUntil = now + RFID_MSG_MS;
  } else {
    Serial.print("DENIED,");
    Serial.println(uid);
    deniedFlashUntil = now + RFID_MSG_MS;
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

// UID as uppercase hex without spaces, for example 125A611A
String uidString()
{
  String s = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) s += "0";
    s += String(rfid.uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

// ---------- LCD: one priority order for the whole system ----------
// gas > intruder > card result > motion > warm-up > safe
void updateLcd(unsigned long now)
{
  String gasTxt = "Gas:" + String(gasValue);

  if (gasAlert) {
    showRows("GAS ALERT!", gasTxt);
  } else if (intrusionOn) {
    showRows("INTRUDER!", "Card to silence");
  } else if (now < grantedFlashUntil) {
    showRows("Access Granted", "Motion Ignored");
  } else if (now < deniedFlashUntil) {
    showRows("Access Denied", "Unknown Card");
  } else if (now < motionFlashUntil) {
    showRows("Motion detected", gasTxt);
  } else if (!calibrated) {
    showRows("Warming up...", gasTxt);
  } else {
    int dots = (now / 500) % 4;           // friend's animated "is safe..." line
    String d = "";
    for (int i = 0; i < dots; i++) d += ".";
    showRows("    The area", "   is safe" + d);
  }
}

void showRows(String top, String bottom)
{
  lcd.setCursor(0, 0);
  lcd.print(padTo16(top));
  lcd.setCursor(0, 1);
  lcd.print(padTo16(bottom));
}

String padTo16(String s)
{
  s = s.substring(0, 16);
  while (s.length() < 16) s += " ";
  return s;
}
