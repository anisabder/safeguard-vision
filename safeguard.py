import os, time, glob, queue, threading
from datetime import datetime
import cv2, numpy as np, requests, serial, face_recognition
from ultralytics import YOLO

# ---------- settings ----------
TOKEN = os.environ["TG_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]
SERIAL_PORT = os.environ.get("SG_PORT", "/dev/ttyACM0")
CAM = os.environ.get("SG_CAM", "0")          # "0" = webcam, or a phone stream URL
THRESHOLD = 0.5                              # lower = stricter face match
CHECK_EVERY = 10                             # run face recognition every N frames
IMGSZ = 320
CONFIRM_FRAMES = 10                          # S2: UNKNOWN for 10 frames in a row
VERIFY_SECONDS = 15                          # after MOTION,1 the PC has this long to confirm
ALARM_COOLDOWN = 60                          # P6: seconds since the last alarm started
RECORD_SECONDS = 30
ACCESS_WINDOW = 10                           # matches the Uno: motion ignored after a card
CAPTURE_TTL = 15 * 60                        # P2: delete motion images after 15 minutes
CAPTURE_DIR, RECORD_DIR = "captures", "recordings"
os.makedirs(CAPTURE_DIR, exist_ok=True)
os.makedirs(RECORD_DIR, exist_ok=True)
from status import Publisher
pub = Publisher()

# ---------- face database (built by enroll.py) ----------
data = np.load("faces.npz")
known_names = data["names"]
known_enc = data["encodings"]

# ---------- Arduino link (optional) ----------
events = queue.Queue()
ard = None
try:
    ard = serial.Serial(SERIAL_PORT, 9600, timeout=0.1)
    print("Arduino connected on", SERIAL_PORT)

    def reader():
        while True:
            line = ard.readline().decode(errors="ignore").strip()
            if line:
                events.put(line)
    threading.Thread(target=reader, daemon=True).start()
except (serial.SerialException, OSError):
    print("No Arduino: PC-only mode. Press m to simulate motion, d to clear an alarm.")

def send(cmd):
    if ard:
        ard.write((cmd + "\n").encode())
    else:
        print("[would send]", cmd)

# ---------- Telegram (background threads, retries, token never printed) ----------
def _tg(method, **kwargs):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    for attempt in range(1, 4):
        try:
            r = requests.post(url, timeout=15, **kwargs)
            if r.status_code == 200:
                return
            print(f"Telegram HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"Telegram attempt {attempt} failed: {type(e).__name__}")
        time.sleep(3)

def tg_text(text):
    threading.Thread(target=_tg, args=("sendMessage",),
                     kwargs={"data": {"chat_id": CHAT_ID, "text": text}},
                     daemon=True).start()

def tg_photo(frame, caption):
    _, buf = cv2.imencode(".jpg", frame)
    threading.Thread(target=_tg, args=("sendPhoto",),
                     kwargs={"data": {"chat_id": CHAT_ID, "caption": caption},
                             "files": {"photo": ("frame.jpg", buf.tobytes(), "image/jpeg")}},
                     daemon=True).start()

# ---------- recognition ----------
def identify(frame, box):
    x1, y1, x2, y2 = box
    crop = frame[max(0, y1):y2, max(0, x1):x2]
    encs = face_recognition.face_encodings(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    if not encs:
        return "face not visible", (0, 255, 255)
    dists = face_recognition.face_distance(known_enc, encs[0])
    best = int(np.argmin(dists))
    if dists[best] < THRESHOLD:
        return str(known_names[best]), (0, 255, 0)
    return "UNKNOWN", (0, 0, 255)

def iou(a, b):
    xa, ya = max(a[0], b[0]), max(a[1], b[1])
    xb, yb = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / (area(a) + area(b) - inter + 1e-6)

# ---------- files ----------
def save_capture(frame):
    path = f"{CAPTURE_DIR}/{datetime.now():%Y%m%d_%H%M%S}.jpg"
    cv2.imwrite(path, frame)
    return path

def cleanup_captures():
    now = time.time()
    for p in glob.glob(f"{CAPTURE_DIR}/*.jpg"):
        if now - os.path.getmtime(p) > CAPTURE_TTL:
            os.remove(p)

# ---------- camera without lag: always keep the newest frame ----------
class LatestFrame:
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.frame, self.ok = None, False
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            ok, f = self.cap.read()
            with self.lock:
                self.ok, self.frame = ok, f
            if not ok:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ok, self.frame.copy()

    def isOpened(self):
        return self.cap.isOpened()

    def release(self):
        self.cap.release()

# ---------- start ----------
model = YOLO("yolov8n.pt")
cap = LatestFrame(int(CAM) if CAM.isdigit() else CAM)
if not cap.isOpened():
    raise SystemExit("Camera not found. Check SG_CAM (0, 1, 2, or the phone stream URL).")

# IDLE -> VERIFY (on MOTION,1) -> ALARM (after 10 unknown frames) -> IDLE (d key or card)
state = "IDLE"
verify_until = 0.0
person_seen = False          # any person seen during this verify window
suppress_until = 0.0         # after a granted card: no alarms, no motion photos
unknown_streak = 0
last_alarm = 0.0
gas_active = False           # from GAS,1 / GAS,0 so the disarm message stays accurate
gas_level = None
uno_ready = False
recorder, record_end = None, 0.0
prev_tracks, frame_idx = [], 0
prev_time, last_cleanup = time.time(), 0.0

# ---------- main loop ----------
while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        time.sleep(0.01)
        continue
    frame_idx += 1
    now = time.time()

    # 1. messages from the Uno
    while not events.empty():
        line = events.get()
        if line == "READY":
            uno_ready = True
            print("Uno ready: PIR and gas monitoring active")
        elif line.startswith("BASELINE,"):
            print("Gas baseline:", line.split(",", 1)[1])
        elif line == "MOTION,1":
            if state == "IDLE" and now >= suppress_until:
                state = "VERIFY"                         # scenario S2 starts here
                verify_until = now + VERIFY_SECONDS
                person_seen, unknown_streak = False, 0
                print(f"MOTION: verifying for {VERIFY_SECONDS} s")
            else:
                print(f"MOTION ignored (state {state})")
        elif line.startswith("GRANTED,"):
            uid = line.split(",", 1)[1]
            suppress_until = now + ACCESS_WINDOW
            was_alarm = state == "ALARM"
            if state in ("VERIFY", "ALARM"):
                state, unknown_streak = "IDLE", 0
            if was_alarm:
                tg_text("Access granted. Intruder alarm cleared." +
                        (" GAS alarm is still active." if gas_active else ""))
            else:
                tg_text(f"Access granted with card {uid}")
            print("GRANTED", uid)
        elif line.startswith("DENIED,"):
            uid = line.split(",", 1)[1]
            tg_text(f"WARNING: unknown card {uid} was scanned")
        elif line == "GAS,1":
            gas_active = True
            tg_text("Safe Guard: GAS LEAK detected")
        elif line == "GAS,0":
            gas_active = False
            tg_text("Safe Guard: gas level is back to normal")
        elif line.startswith("LEVEL,"):
            try:
                gas_level = int(line.split(",", 1)[1])
            except ValueError:
                pass
        else:
            print("Uno:", line)

    # 2. detect and identify people
    result = model.predict(frame, classes=[0], conf=0.5, imgsz=IMGSZ, verbose=False)[0]
    tracks = []
    for b in result.boxes:
        box = tuple(map(int, b.xyxy[0]))
        match = max(prev_tracks, key=lambda t: iou(t[0], box), default=None)
        if match and iou(match[0], box) > 0.3 and frame_idx % CHECK_EVERY != 0:
            label, color = match[1], match[2]
        else:
            label, color = identify(frame, box)
        tracks.append((box, label, color))
        x1, y1, x2, y2 = box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    prev_tracks = tracks

    # 3. verify window: anyone seen counts, and with nobody in view a movement photo is sent
    if state == "VERIFY":
        if tracks:
            person_seen = True
        if now > verify_until:
            if not person_seen and now >= suppress_until:
                path = save_capture(frame)
                tg_photo(frame, f"Movement spotted at {datetime.now():%H:%M:%S}")
                print("movement image saved:", path)
            state = "IDLE"

    # 4. unknown person confirmed during verify: buzzer, photo, recording
    unknown_now = any(t[1] == "UNKNOWN" for t in tracks)
    unknown_streak = unknown_streak + 1 if unknown_now else 0
    if (state == "VERIFY" and unknown_streak >= CONFIRM_FRAMES
            and now >= suppress_until and now - last_alarm > ALARM_COOLDOWN):
        state, last_alarm = "ALARM", now
        send("BUZZER,ON")
        tg_photo(frame, f"ALERT: unknown person at {datetime.now():%H:%M:%S}")
        recorder = cv2.VideoWriter(f"{RECORD_DIR}/{datetime.now():%Y%m%d_%H%M%S}.mp4",
                                   cv2.VideoWriter_fourcc(*"mp4v"), 15,
                                   (frame.shape[1], frame.shape[0]))
        record_end = now + RECORD_SECONDS
        print("ALARM started")

    # 5. write the recording, stop when time is up
    if recorder:
        recorder.write(frame)
        if now > record_end:
            recorder.release()
            recorder = None
            print("recording saved")

    # 6. delete old motion images every 30 seconds
    if now - last_cleanup > 30:
        cleanup_captures()
        last_cleanup = now

    # 7. display and keys
    fps = 1 / max(now - prev_time, 1e-6)
    prev_time = now
    status = f"VERIFY {max(0, int(verify_until - now))}s" if state == "VERIFY" else state
    uno_txt = "none (PC only)" if ard is None else ("ready" if uno_ready else "warming up")
    gas_txt = f"  GAS: {gas_level}" if gas_level is not None else ""
    color = (0, 0, 255) if state == "ALARM" else (0, 255, 0)
    cv2.putText(frame, f"STATE: {status}  UNO: {uno_txt}  FPS: {fps:.1f}{gas_txt}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.imshow("Safe Guard", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == ord("m") and state == "IDLE" and now >= suppress_until:   # simulate PIR
        state, verify_until = "VERIFY", now + VERIFY_SECONDS
        person_seen, unknown_streak = False, 0
        print(f"simulated motion: verifying for {VERIFY_SECONDS} s")
    if key == ord("d") and state == "ALARM":       # clear the alarm from the PC
        send("BUZZER,OFF")
        state, unknown_streak = "IDLE", 0
        tg_text("Intruder alarm cleared from the PC" +
                (". GAS alarm is still active." if gas_active else ""))

if recorder:
    recorder.release()
cap.release()
cv2.destroyAllWindows()
