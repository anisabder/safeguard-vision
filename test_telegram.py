import os, requests

token = os.environ["TG_TOKEN"]
chat_id = os.environ["TG_CHAT_ID"]

r = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data={"chat_id": chat_id, "text": "Nroho nchoufou LFATAYAT ?"},
    timeout=10,
)
print(r.status_code, r.json())
