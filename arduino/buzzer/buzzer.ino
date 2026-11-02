const int buzzerPin = 8; // Connect buzzer positive pin to digital pin 8

void setup() {
  pinMode(buzzerPin, OUTPUT);
}

void loop() {
  tone(buzzerPin, 1000); // Send a 1000 Hz tone to the buzzer
  delay(1000);           // Wait for 1 second
  noTone(buzzerPin);     // Stop the tone
  delay(1000);           // Wait for 1 second
}
