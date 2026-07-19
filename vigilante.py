# Vigilante Pastillero: revisa las tomas pendientes y envia recordatorios push.
import os, json
from datetime import datetime
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore, messaging

cred = credentials.Certificate(json.loads(os.environ["FIREBASE_SA"]))
firebase_admin.initialize_app(cred)
db = firestore.client()

TZ = ZoneInfo("Europe/Madrid")
now = datetime.now(TZ)
ymd = now.strftime("%Y%m%d")
iso = now.strftime("%Y-%m-%d")
now_min = now.hour * 60 + now.minute
VENTANA = 90
APP_URL = "https://pastillero-19633.web.app/?toma=1"

def to_min(t):
    return int(t[:2]) * 60 + int(t[3:5])

enviados = 0
for u in db.collection("users").stream():
    uid = u.id
    data = u.to_dict() or {}
    tokens = data.get("fcmTokens") or []
    if not tokens:
        continue

    meds = list(db.collection("users").document(uid).collection("meds").stream())
    if not meds:
        continue

    doses = {}
    for d in db.collection("users").document(uid).collection("doses").where("date", "==", iso).stream():
        doses[d.id] = d.to_dict()

    for m in meds:
        md = m.to_dict() or {}
        mid = m.id
        for t in (md.get("times") or []):
            tmin = to_min(t)
            if not (tmin <= now_min <= tmin + VENTANA):
                continue

            dose_id = f"{ymd}_{mid}_{t.replace(':', '')}"
            rec = doses.get(dose_id)
            if rec and rec.get("taken") is True:
                continue

            rem_ref = db.collection("users").document(uid).collection("remindersSent").document(dose_id)
            if rem_ref.get().exists:
                continue

            nombre = md.get("name", "tu medicacion")
            nota = md.get("note")
            body = f"No olvides tomar {nombre}" + (f" ({nota})" if nota else "")

            msg = messaging.MulticastMessage(
                tokens=tokens,
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        title="Pastillero", body=body, icon="/icon-192.png"
                    ),
                    fcm_options=messaging.WebpushFCMOptions(link=APP_URL),
                ),
            )
            resp = messaging.send_each_for_multicast(msg)
            enviados += resp.success_count
            rem_ref.set({"sentAt": firestore.SERVER_TIMESTAMP, "med": nombre, "time": t})

            malos = []
            for i, r in enumerate(resp.responses):
                if not r.success and r.exception is not None:
                    e = str(r.exception)
                    if "not-registered" in e or "invalid-argument" in e or "not-found" in e:
                        malos.append(tokens[i])
            if malos:
                db.collection("users").document(uid).update({"fcmTokens": firestore.ArrayRemove(malos)})

print(f"[{now.isoformat()}] Recordatorios enviados: {enviados}")
