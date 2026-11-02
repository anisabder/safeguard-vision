#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <SPI.h> 
#include <MFRC522.h> 
#define SS_PIN  7
#define RST_PIN  9
 
byte authorizedUID[] = {0x12, 0x5A, 0x61, 0x1A};
MFRC522 rfid(SS_PIN, RST_PIN); 
MFRC522::MIFARE_Key key;
LiquidCrystal_I2C lcd(0x27,16,2);

int detectm = 2;
unsigned long ignoreMotionUntil = 0;
unsigned long pretime = 0;
int dot;
int detectg = A1;
int motor = 7;
int led = 4;
void setup()  
{
  lcd.init();
  lcd.backlight();
  lcd.begin(16, 2);
  pinMode(detectm , INPUT);
  pinMode(detectg , INPUT);
  pinMode(motor , OUTPUT);
  pinMode(led, OUTPUT);
  Serial.begin(9600);
  SPI.begin(); 
  rfid.PCD_Init();
}

void loop()
{
  int Motion = digitalRead(detectm);
  int Gas = analogRead(detectg);
  Serial.println(Gas);
  digitalWrite(motor , Gas > 60 ? HIGH : LOW);
 if(Gas > 60){
  
   lcd.setCursor(0, 0);
   lcd.print("  Gas detected  ");
   digitalWrite(led,HIGH);
   lcd.setCursor(0, 1);
   lcd.print("    Gas leak    ");
  }else  if (Motion == HIGH && millis() > ignoreMotionUntil) { 
    lcd.setCursor(0, 0);
    lcd.print("Movment detcted:");
    lcd.setCursor(0, 1);
    lcd.print(" Intruder ahead ");
    digitalWrite(led, HIGH);
    checkRFID();
  }else {
    unsigned long currtime = millis();
    if (currtime - pretime >= 500) {
    pretime = currtime;
      
    lcd.setCursor(0, 0);
    lcd.print("    The area    ");
      
    lcd.setCursor(0, 1);
      if (dot == 0) {
        lcd.print("   is safe      ");
      }else if (dot == 1) {
        lcd.print("   is safe.     ");
      }else if (dot == 2) {
        lcd.print("   is safe..    ");
      }else if (dot == 3) {  
        lcd.print("   is safe...   ");
      } dot++;
      if (dot >3) {
        dot = 0;
      }    
  }
}
digitalWrite(led, LOW);
}
void checkRFID() {
  // Look for new cards
  if (!rfid.PICC_IsNewCardPresent()) {
    return;
  }
  // Select one of the cards
  if (!rfid.PICC_ReadCardSerial()) {
    return;
  }

  // Check if UID matches authorizedUID
  boolean match = true;
  for (byte i = 0; i < 4; i++) {
    if (rfid.uid.uidByte[i] != authorizedUID[i]) {
      match = false;
      break;
    }
  }

  lcd.clear();
  if (match) {
    lcd.setCursor(0, 0);
    lcd.print(" Access Granted ");
    lcd.setCursor(0, 1);
    lcd.print(" Motion Ignored ");
    delay(2000);
    // Suppress motion alerts for 10 seconds (10000 ms)
    ignoreMotionUntil = millis() + 10000; 
  } else {
    lcd.setCursor(0, 0);
    lcd.print("  Access Denied ");
    lcd.setCursor(0, 1);
    lcd.print(" Unknown Card   ");
    delay(2000);
  }
  
  // Halt PICC and stop crypto
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  lcd.clear();
}
void printHex(byte *buffer, byte bufferSize) {
  for (byte i = 0; i < bufferSize; i++) {
    Serial.print(buffer[i] < 0x10 ? " 0" : " ");
    Serial.print(buffer[i], HEX);
  }
}