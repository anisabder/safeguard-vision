import os
import numpy as np
import face_recognition

IMG_EXT = (".jpg", ".jpeg", ".png")
names, encodings = [], []

for person in sorted(os.listdir("faces")):
    folder = os.path.join("faces", person)
    # skip the .venv folder and any loose files
    if person.startswith(".") or not os.path.isdir(folder):
        continue

    usable = 0
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(IMG_EXT):
            continue
        img = face_recognition.load_image_file(os.path.join(folder, fname))
        found = face_recognition.face_encodings(img)
        if found:
            names.append(person)
            encodings.append(found[0])
            usable += 1
        else:
            print(f"  no face found in {person}/{fname}, skipped")
    print(f"{person}: {usable} usable photos")

np.savez("faces.npz", names=np.array(names), encodings=np.array(encodings))
print(f"Saved faces.npz with {len(set(names))} enrolled person(s)")
