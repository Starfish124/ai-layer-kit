"""Zet de controlekamer-jobs in xyOps — idempotent op titel.

xyOps is het lokale ops-vlak (ADR-006): het plant, bewaart en alarmeert, maar
meet niets. Elke job hier roept `controlroom.py` aan en leest wat dat zegt.

    python3.12 xyops_setup.py            # maakt/actualiseert de events
    python3.12 xyops_setup.py --toon     # alleen laten zien wat er staat

Sleutel: ~/.config/ai-layer-kit/xyops.json  { "url": "http://127.0.0.1:5522", "api_key": "…" }
(aanmaken in xyOps: Settings → API Keys; 0600; nooit in git.)
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CFG = Path.home() / ".config/ai-layer-kit/xyops.json"
KIT = Path(__file__).resolve().parent
MANIFEST = Path.home() / "durabo-platform/layers.json"
PY = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"


def api(cfg, naam, body=None):
    req = urllib.request.Request(f"{cfg['url']}/api/app/{naam}/v1",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"X-API-Key": cfg["api_key"],
                                          "Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{naam}: HTTP {e.code} — {e.read().decode(errors='replace')[:400]}")
    if d.get("code") not in (0, "0", None):
        raise SystemExit(f"{naam}: {d.get('code')} — {d.get('description')}")
    return d


def script(*args):
    """Elke job is dezelfde regel: de kit, de manifest, en wat er gemeten moet worden."""
    return "#!/bin/sh\nset -e\ncd " + str(KIT) + "\n" + \
        " ".join([PY, "controlroom.py", str(MANIFEST), *args]) + "\n"


EVENTS = [
    dict(title="Controlekamer · meet (elk kwartier)",
         params={"script": script("--run", "--xy")},
         triggers=[{"type": "interval", "enabled": True, "start": int(time.time()), "duration": 900}],
         limits=[{"type": "time", "enabled": True, "duration": 600}]),
    dict(title="Controlekamer · ketens verifiëren (elk uur)",
         params={"script": script("--tally", "ketens_intact") +
                 'test "$(' + " ".join([PY, "controlroom.py", str(MANIFEST), "--tally", "ketens_intact"]) + ')" = "1"\n'},
         triggers=[{"type": "interval", "enabled": True, "start": int(time.time()), "duration": 3600}],
         limits=[{"type": "time", "enabled": True, "duration": 120}]),
    dict(title="Controlekamer · RBAC-sonde (dagelijks 07:00)",
         params={"script": "#!/bin/sh\ncd " + str(Path.home() / "durabo-platform") +
                 "\npwsh -NoProfile -File entra/verify-mailbox-rbac.ps1; rc=$?\n"
                 "# exit 2 = kon niet meten: geen fout, wel zichtbaar\n"
                 "[ $rc -eq 2 ] && { echo '{\"xy\":true,\"warning\":\"sonde niet uitvoerbaar\"}'; exit 0; }\nexit $rc\n"},
         triggers=[{"type": "schedule", "enabled": True, "hours": [7], "minutes": [0], "timezone": "Europe/Amsterdam"}],
         limits=[{"type": "time", "enabled": True, "duration": 300}]),
    dict(title="Controlekamer · export naar Downloads (dagelijks 18:00)",
         params={"script": script("--run", "--export", str(Path.home() / "Downloads"))},
         triggers=[{"type": "schedule", "enabled": True, "hours": [18], "minutes": [0], "timezone": "Europe/Amsterdam"}],
         limits=[{"type": "time", "enabled": True, "duration": 600}]),
]


def bestaande(cfg):
    """Alle events op titel. Endpointnaam volgens de docs; valt terug op een lege lijst."""
    for naam in ("get_events",):
        try:
            d = api(cfg, naam)
            rows = d.get("rows") or d.get("events") or d.get("data") or []
            return {e["title"]: e for e in rows}
        except SystemExit:
            continue
        except Exception:
            continue
    return {}


def main():
    if not CFG.exists():
        sys.exit(f"geen {CFG} — maak eerst een API-sleutel aan in xyOps")
    cfg = json.loads(CFG.read_text())
    er_al = bestaande(cfg)
    if "--toon" in sys.argv:
        for t in er_al:
            print("·", t)
        return
    for ev in EVENTS:
        body = {"enabled": True, "category": "general", "plugin": "shellplug",
                "targets": ["main"], "algo": "random", **ev}
        if ev["title"] in er_al:
            api(cfg, "update_event", {"id": er_al[ev["title"]]["id"], **body})
            print("bijgewerkt:", ev["title"])
        else:
            d = api(cfg, "create_event", body)
            print("aangemaakt:", ev["title"], d.get("id", ""))


if __name__ == "__main__":
    main()
