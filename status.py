# Writes the live system state to status.json for the web dashboard.
# safeguard.py calls Publisher; dashboard.py reads the file. They run as separate programs,
# so a dashboard crash can never affect detection or the alarm.
import json, os, time, threading
from datetime import datetime

PATH = os.environ.get("SG_STATUS", "status.json")
MAX_EVENTS = 30

class Publisher:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"state": "IDLE", "verify_left": 0, "uno": "starting",
                     "gas_level": None, "gas_active": False, "events": []}
        self.last_write = 0.0

    def update(self, **fields):
        with self.lock:
            self.data.update(fields)
        self.flush()

    def event(self, kind, text):
        # kind: alarm, warn, ok or info (controls the colour on the dashboard)
        with self.lock:
            self.data["events"].append({"time": datetime.now().strftime("%H:%M:%S"),
                                        "kind": kind, "text": text})
            self.data["events"] = self.data["events"][-MAX_EVENTS:]
        self.flush(force=True)

    def flush(self, force=False):
        now = time.time()
        if not force and now - self.last_write < 0.5:   # at most twice a second
            return
        self.last_write = now
        with self.lock:
            payload = dict(self.data, ts=now)
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, PATH)                           # atomic: never a half-written file
