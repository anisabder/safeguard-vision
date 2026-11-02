# Safe Guard

A smart security station built with an Arduino Uno and a PC. The Uno senses motion, gas and RFID cards. The PC watches a camera, tells enrolled people from strangers, and sends alerts to Telegram. A small web dashboard on the owner's PC shows what the system is doing.

Built for an IEEE student competition.

## What it does

| Situation | What happens |
|---|---|
| Motion, enrolled person | Nothing. Their name is shown in green on the camera window |
| Motion, stranger | Buzzer and LED turn on, the LCD shows INTRUDER, Telegram gets a photo, and a 30 s recording is saved |
| Motion, nobody in view | Telegram gets a "Movement spotted" photo, which is deleted after 15 minutes |
| Gas or smoke | The Uno sounds the buzzer by itself and Telegram gets a message. The alarm clears when the gas level falls |
| Authorised RFID card | Silences the intruder alarm and ignores motion for 10 s |
| Unknown RFID card | The LCD shows Access Denied and Telegram gets a warning |

## How it works

```
 PIR, MQ-2, RFID card  -->  Arduino Uno  --USB serial-->  PC (safeguard.py)
 LCD, buzzer, LED      <--                <--              camera + YOLO + face recognition
                                                           |-- Telegram alerts
                                                           |-- recordings
                                                           '-- status.json --> dashboard.py (this PC only)
```

1. The PIR sends `MOTION,1`. The PC enters a 15 s verification window.
2. YOLOv8 finds people in the camera image and `face_recognition` compares each face with the enrolled people.
3. If an unknown face is seen for 10 frames in a row, the PC sends `BUZZER,ON`, a Telegram photo, and starts a recording.
4. An authorised card tap (or the `d` key on the PC) clears the intruder alarm.
5. Gas is handled on the Uno itself, so the gas alarm works even if the PC is off.

## Hardware

| Part | Uno pin |
|---|---|
| Arduino Uno R3 | - |
| PIR motion sensor (HC-SR501) | D2 |
| Gas sensor (MQ-2), analog output | A1 |
| Active buzzer, through a 220 ohm resistor | D8 |
| Status LED | D4 |
| RFID reader (MFRC522), SS and RST | D7, D9 |
| RFID reader, SPI | D11 (MOSI), D12 (MISO), D13 (SCK) |
| LCD 16x2 with I2C backpack (address 0x27) | A4 (SDA), A5 (SCL) |
| Webcam or phone camera | PC |

The MFRC522 runs on 3.3 V. Do not connect it to 5 V.

## Serial protocol (9600 baud, one text line per message)

| Message | Direction | Meaning |
|---|---|---|
| `READY` | Uno to PC | Warm-up and gas calibration finished |
| `BASELINE,<n>` | Uno to PC | Clean-air gas reading used for the alarm limits |
| `MOTION,1` | Uno to PC | PIR movement, once per movement |
| `GAS,1` / `GAS,0` | Uno to PC | Gas alarm started / cleared |
| `LEVEL,<n>` | Uno to PC | Gas reading, once per second |
| `GRANTED,<UID>` / `DENIED,<UID>` | Uno to PC | Authorised / unknown card |
| `BUZZER,ON` / `BUZZER,OFF` | PC to Uno | Intruder alarm on / off |

## Setup

### 1. Arduino

Install [arduino-cli](https://arduino.github.io/arduino-cli/), then:

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr
arduino-cli lib install "LiquidCrystal I2C" "MFRC522"
cd arduino
arduino-cli compile --fqbn arduino:avr:uno SafeGuard_arduino
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno SafeGuard_arduino
```

Use the port shown by `arduino-cli board list`. Run compile and upload as two separate commands.

To add your own card, tap it once. Telegram sends "unknown card <UID>". Copy those bytes into `authorizedUID` in the sketch and upload again.

### 2. PC

You need Python 3, a camera, and a C++ compiler with CMake (`dlib` is built from source). On Arch Linux:

```bash
sudo pacman -S --needed base-devel cmake python
```

Give your user access to the camera and the serial port, then log out and back in. On Arch the groups are `video` and `uucp` (on Debian or Ubuntu: `video` and `dialout`):

```bash
sudo usermod -aG video,uucp $USER
```

Create an environment and install the libraries:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The first run downloads the `yolov8n.pt` model, so you need internet once.

### 3. Telegram

1. In Telegram, open **@BotFather**, send `/newbot`, and copy the token.
2. Open your bot and press **Start**. The bot cannot see a chat until someone writes to it.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number in `"chat":{"id": ...}`.
4. Keep the token and chat ID in a file outside this project, for example `~/.config/safeguard.env`:

```bash
export TG_TOKEN="your-token"
export TG_CHAT_ID="your-chat-id"
```

5. Load it in every terminal that runs the program, and test it:

```bash
source ~/.config/safeguard.env
python test_telegram.py
```

You should get `200` and a message in Telegram.

### 4. Enrol faces

Create one folder per person inside `faces/`. The folder name is the label shown on screen. Use 5 to 15 clear photos per person, one person per photo.

```
faces/
  alice/
    1.jpg
    2.jpg
  bob/
    1.jpg
```

Build the face database (run it again whenever the photos change):

```bash
python enroll.py
```

### 5. Run

```bash
source .venv/bin/activate
source ~/.config/safeguard.env
python safeguard.py
```

Close any serial monitor first, because only one program can use the Uno. Starting the program resets the Uno, so wait about 60 s for `Uno ready` in the terminal.

Environment variables you can set:

| Variable | Default | Use |
|---|---|---|
| `SG_PORT` | `/dev/ttyACM0` | Serial port of the Uno |
| `SG_CAM` | `0` | Camera index, or a stream URL |

Without an Uno the program runs in PC-only mode and prints `[would send]` instead of sending commands.

Keys in the camera window:

| Key | Action |
|---|---|
| `m` | Simulate a PIR trigger (when IDLE) |
| `d` | Clear the intruder alarm (when in ALARM) |
| `q` | Quit |

## Dashboard (owner's PC only)

The dashboard shows the system state, the sensor board status, the gas level and the latest events. It never shows camera images or photos.

Run it from the same folder as `safeguard.py`, in a second terminal:

```bash
source .venv/bin/activate
export DASH_TOKEN="$(openssl rand -hex 8)"
echo "$DASH_TOKEN"
python dashboard.py
```

Open `http://127.0.0.1:8000/?key=<your token>` in a browser on the same PC.

It listens on `127.0.0.1` only, so other devices cannot reach it. Do not expose it to the internet.

## Settings

The main values are at the top of `safeguard.py`:

| Setting | Default | Meaning |
|---|---|---|
| `THRESHOLD` | 0.5 | Face match strictness (lower is stricter) |
| `CHECK_EVERY` | 10 | Run face recognition every N frames |
| `CONFIRM_FRAMES` | 10 | Unknown frames in a row needed for an alarm |
| `VERIFY_SECONDS` | 15 | Check window after a motion event |
| `ALARM_COOLDOWN` | 60 | Seconds before another alarm can start |
| `RECORD_SECONDS` | 30 | Length of an intruder recording |
| `ACCESS_WINDOW` | 10 | Seconds motion is ignored after an authorised card (must match the sketch) |

On the Uno, the warm-up times and gas limits are constants at the top of `SafeGuard_arduino.ino`.

## Privacy and security

- `faces/` (photos) and `faces.npz` (face data) are personal data. They are listed in `.gitignore` and must never be committed.
- The Telegram token is read from the environment and must never be written in the code.
- `recordings/` and `captures/` stay on your PC.
- The sketch contains the UID of the authorised card. Anyone who knows it can copy the card, so use a placeholder if you publish the repository.

## Project layout

```
safeguard.py        main PC program
status.py           writes status.json for the dashboard
dashboard.py        local web dashboard
enroll.py           builds faces.npz from the photos in faces/
test_telegram.py    sends one test message
requirements.txt    Python libraries
arduino/
  SafeGuard_arduino/
    SafeGuard_arduino.ino    Uno sketch
faces/              one folder per person (not committed)
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `KeyError: 'TG_TOKEN'` | Run `source ~/.config/safeguard.env` in the same terminal |
| Telegram `HTTP 401` | The token is wrong or revoked |
| Telegram `HTTP 400`, chat not found | Wrong chat ID, or you never pressed Start on the bot |
| `No Arduino: PC-only mode` | Check the cable and port, close any serial monitor, check group permissions |
| `Camera not found` | Try `SG_CAM=1`, or check the stream URL |
| `No module named ...` | Activate the environment with `source .venv/bin/activate` |
