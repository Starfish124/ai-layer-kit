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


def _canonieke_checkout():
    """Weiger te draaien vanuit een gekoppelde worktree.

    Elke job hieronder bakt KIT in zijn `cd` — dus draaien vanuit een worktree herschrijft
    *alle* productiejobs naar dat tijdelijke pad, stil, ook de jobs die niets met je werk te
    maken hebben. Dat is één keer echt gebeurd (31 aug 2026) en was pas zichtbaar door de
    scripts terug te lezen met get_events.

    In een gekoppelde worktree wijst --git-dir naar .git/worktrees/<naam> en --git-common-dir
    naar de echte .git; in de hoofdcheckout zijn ze gelijk.
    """
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "--git-dir", "--git-common-dir"],
                           cwd=KIT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return                      # geen git = geen oordeel; niet tegenhouden
    if r.returncode != 0:
        return
    regels = r.stdout.split()
    if len(regels) == 2 and Path(regels[0]).resolve() != Path(regels[1]).resolve():
        sys.exit(f"xyops_setup.py draait vanuit een worktree ({KIT}).\n"
                 f"Elke job zou zijn cd naar dat pad krijgen. Draai hem uit de hoofdcheckout.")
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


def runs_script():
    """Zelfde patroon als script(), maar schrijft de pagina weg — een run-overzicht is iets om te lezen."""
    return "#!/bin/sh\nset -e\ncd " + str(KIT) + "\n" + \
        " ".join([PY, "controlroom.py", str(MANIFEST), "--runs"]) + \
        ' > /tmp/runs.html && echo "runs gemeten"\n'


EVENTS = [
    dict(title="Controlekamer · runs",
         params={"script": runs_script()},
         triggers=[{"type": "manual", "enabled": True}],
         limits=[{"type": "time", "enabled": True, "duration": 600}]),
    dict(title="Controlekamer · meet (elk kwartier)",
         params={"script": script("--run", "--xy")},
         triggers=[{"type": "manual", "enabled": True}, {"type": "interval", "enabled": True, "start": int(time.time()), "duration": 900}],
         limits=[{"type": "time", "enabled": True, "duration": 600}]),
    dict(title="Controlekamer · ketens verifiëren (elk uur)",
         params={"script": script("--tally", "ketens_intact") +
                 'test "$(' + " ".join([PY, "controlroom.py", str(MANIFEST), "--tally", "ketens_intact"]) + ')" = "1"\n'},
         triggers=[{"type": "manual", "enabled": True}, {"type": "interval", "enabled": True, "start": int(time.time()), "duration": 3600}],
         limits=[{"type": "time", "enabled": True, "duration": 120}]),
    dict(title="Controlekamer · RBAC-sonde (dagelijks 07:00)",
         params={"script": "#!/bin/sh\ncd " + str(Path.home() / "durabo-platform") +
                 "\npwsh -NoProfile -File entra/verify-mailbox-rbac.ps1; rc=$?\n"
                 "# exit 2 = kon niet meten: geen fout, wel zichtbaar\n"
                 "[ $rc -eq 2 ] && { echo '{\"xy\":true,\"warning\":\"sonde niet uitvoerbaar\"}'; exit 0; }\nexit $rc\n"},
         triggers=[{"type": "manual", "enabled": True}, {"type": "schedule", "enabled": True, "hours": [7], "minutes": [0], "timezone": "Europe/Amsterdam"}],
         limits=[{"type": "time", "enabled": True, "duration": 300}]),
    dict(title="Controlekamer · export naar Downloads (dagelijks 18:00)",
         params={"script": script("--run", "--export", str(Path.home() / "Downloads"))},
         triggers=[{"type": "manual", "enabled": True}, {"type": "schedule", "enabled": True, "hours": [18], "minutes": [0], "timezone": "Europe/Amsterdam"}],
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


WORKFLOW_TITEL = "Controlekamer · meet → ketens → export"


def workflow(cfg, er_al):
    """Eén visuele workflow over drie bestaande events: alleen succes stroomt door.

    Node-vorm en velden komen uit lib/util.js en lib/workflow.js van xyOps zelf:
    een trigger-node heeft geen data, een event-node wijst met `data.event` naar
    een event (dat een handmatige trigger nodig heeft), een verbinding draagt
    `condition`. Posities hier zijn cosmetisch — dit is xyOps' eigen canvas.
    """
    ids = {t: er_al[t]["id"] for t in er_al if t.startswith("Controlekamer · ")}
    meet = ids["Controlekamer · meet (elk kwartier)"]
    ketens = ids["Controlekamer · ketens verifiëren (elk uur)"]
    export = ids["Controlekamer · export naar Downloads (dagelijks 18:00)"]
    nodes = [
        {"id": "ntrig", "type": "trigger", "x": 40, "y": 140},
        {"id": "nmeet", "type": "event", "x": 300, "y": 140, "data": {"event": meet}},
        {"id": "nket", "type": "event", "x": 560, "y": 140, "data": {"event": ketens}},
        {"id": "nexp", "type": "event", "x": 820, "y": 140, "data": {"event": export}},
    ]
    conns = [
        {"id": "c1", "source": "ntrig", "dest": "nmeet"},
        {"id": "c2", "source": "nmeet", "dest": "nket", "condition": "success"},
        {"id": "c3", "source": "nket", "dest": "nexp", "condition": "success"},
    ]
    body = {"title": WORKFLOW_TITEL, "type": "workflow", "enabled": True, "category": "general",
            "targets": ["main"], "algo": "random",
            "triggers": [{"id": "ntrig", "type": "manual", "enabled": True}],
            "workflow": {"nodes": nodes, "connections": conns},
            "limits": [{"type": "time", "enabled": True, "duration": 1200}]}
    # ⚠️ `update_event` strijkt `type: "workflow"` eraf — daarna faalt de job met
    # "Plugin not found: _workflow". Een workflow vervang je dus, je werkt hem niet bij.
    if WORKFLOW_TITEL in er_al:
        api(cfg, "delete_event", {"id": er_al[WORKFLOW_TITEL]["id"]})
    d = api(cfg, "create_event", body)
    print("(her)aangemaakt:", WORKFLOW_TITEL, d.get("id", ""))


STROOM_TITEL = "Durabo AI-laag · Stroom"


def stroom_workflow(cfg, er_al):
    """De Stroom als xyOps-workflow: elke knoop is een meting die draait.

    Dit is geen plaatje van de systemen. Elke systeemknoop is een echte job die
    `controlroom.py --systeem <module>` draait op de satelliet: hij licht op
    terwijl hij loopt, kleurt rood als een grens of een test valt, en laat een
    jobrapport achter met de tabel en het bewijs. De join wacht op alle twaalf,
    de laatste knoop zet de telling in de bucket.

    De knopen komen uit `layers.json` — niet met de hand geplaatst, net als op de
    eigen Stroom-pagina (ADR-005/007). Een systeem erbij in de manifest is een
    knoop erbij hier.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    systemen = manifest.get("systemen", [])

    midden = 60 + len(systemen) * 44
    # Elke trigger krijgt zijn eigen knoop: de tekenaar zoekt per trigger-knoop de
    # trigger met hetzelfde id, en de motor start bij de knoop van de trigger die
    # vuurde. Een trigger zónder knoop start dus een lege workflow.
    triggers = [{"id": "ntrigman", "type": "manual", "enabled": True},
                {"id": "ntrigdag", "type": "schedule", "enabled": True, "hours": [8],
                 "minutes": [0], "timezone": "Europe/Amsterdam"}]
    nodes = [
        {"id": "ntrigman", "type": "trigger", "x": 40, "y": midden - 60},
        {"id": "ntrigdag", "type": "trigger", "x": 40, "y": midden + 60},
        # ⚠️ de tekenaar leest `data.body` (niet `text`): een ander veld laat
        # `undefined.trim()` klappen, en dan tekent de héle kaart niets meer.
        {"id": "nnote", "type": "note", "x": 20, "y": 20, "data": {"wide": True, "body":
            "**Elke knoop is een meting, geen plaatje.**\n\n"
            "Een systeemknoop draait `controlroom.py --systeem <module>`: rood zodra die "
            "module een verboden import doet, ergens schrijft, de klok leest, of zijn "
            "eigen test valt. Groen betekent gemeten, niet beloofd.\n\n"
            "De knopen komen uit `layers.json`; met de hand bijtekenen heeft geen zin."}},
    ]
    conns = []
    for i, s_ in enumerate(systemen):
        nid = "n" + s_["module"]
        nodes.append({
            "id": nid, "type": "job", "x": 380, "y": 60 + i * 88,
            "data": {"label": f"{s_['nr']} · {s_['naam']}", "icon": "",
                     "category": "general", "targets": ["main"], "algo": "random",
                     "plugin": "shellplug",
                     "params": {"script": script("--systeem", s_["module"]), "annotate": False}},
        })
        conns.append({"id": f"ctm{i}", "source": "ntrigman", "dest": nid})
        conns.append({"id": f"ctd{i}", "source": "ntrigdag", "dest": nid})
        # 'complete' = altijd; een rood systeem mag de samenvatting niet tegenhouden,
        # anders zie je juist niets op de dag dat er iets mis is.
        conns.append({"id": f"cj{i}", "source": nid, "dest": "njoin", "condition": "complete"})

    # De bewakingsknoop hangt naast de systemen: die meten of de code zich
    # gedraagt, deze of de omgeving dat doet. Beide moeten groen zijn.
    nodes.append({"id": "nbewaking", "type": "job", "x": 380, "y": 60 + len(systemen) * 88,
                  "data": {"label": "Bewaking · loopback, funnel, sleutels, poort", "icon": "",
                           "category": "general", "targets": ["main"], "algo": "random",
                           "plugin": "shellplug",
                           "params": {"script": script("--bewaking"), "annotate": False}}})
    conns.append({"id": "ctmb", "source": "ntrigman", "dest": "nbewaking"})
    conns.append({"id": "ctdb", "source": "ntrigdag", "dest": "nbewaking"})
    conns.append({"id": "cjb", "source": "nbewaking", "dest": "njoin", "condition": "complete"})

    nodes.append({"id": "njoin", "type": "controller", "x": 780,
                  "y": midden, "data": {"controller": "join"}})
    nodes.append({"id": "nsam", "type": "job", "x": 1060, "y": midden,
                  "data": {"label": "Samenvatting → bucket", "icon": "",
                           "category": "general", "targets": ["main"], "algo": "random",
                           "plugin": "shellplug",
                           "params": {"script": script("--run", "--xy"), "annotate": False}}})
    conns.append({"id": "cs", "source": "njoin", "dest": "nsam"})

    body = {"title": STROOM_TITEL, "type": "workflow", "enabled": True, "category": "general",
            "targets": ["main"], "algo": "random",
            "triggers": triggers,
            "workflow": {"nodes": nodes, "connections": conns},
            "limits": [{"type": "time", "enabled": True, "duration": 1800}]}

    # update_event strijkt `type` eraf, dus vervangen = verwijderen en opnieuw maken.
    if STROOM_TITEL in er_al:
        api(cfg, "delete_event", {"id": er_al[STROOM_TITEL]["id"]})
    d = api(cfg, "create_event", body)
    print(f"aangemaakt: {STROOM_TITEL} ({len(systemen)} systeemknopen) {d.get('id','')}")


TREND_TITEL = "Durabo trendmotor · nu, opkomend, voorspeld"
TREND_REPO = Path.home() / "durabo-trend-engine"
# De motor draait onder uv: system python heeft geen pandas, en brew-python mist expat.
TREND_UV = ("uv run --with pandas --with scikit-learn --with statsmodels "
            "--with playwright --with open-clip-torch python")


def trend_script(*args):
    return ("#!/bin/sh\nset -e\ncd " + str(TREND_REPO) + "\n" +
            "export PATH=/opt/homebrew/bin:$PATH\n" + " ".join(args) + "\n")


def trend_workflow(cfg, er_al):
    """De trendmotor als xyOps-workflow.

    De motor zelf is één proces (verzamelen → signaal → ontdekking → forecast);
    die valt niet in knopen te knippen zonder hem te herschrijven, dus dat is één
    knoop en dat zegt de kaart ook. Wat er ná die knoop hangt zijn drie *beelden*
    op dezelfde meting: wat draait nu, wat komt op, wat voorspelt hij. Drie
    knopen omdat het drie vragen zijn, één meting omdat het één waarheid is.

    De conditieknoop draait eerst en apart: hij zegt of de feed vers genoeg is om
    iets over te beweren. Een dashboard dat een feed van gisteren als 'nu'
    presenteert is erger dan een leeg dashboard.
    """
    nodes = [
        {"id": "ntrigman", "type": "trigger", "x": 40, "y": 300},
        {"id": "ntrigcyc", "type": "trigger", "x": 40, "y": 420},
        {"id": "nnote", "type": "note", "x": 20, "y": 20, "data": {"wide": True, "body":
            "**Vier lagen, één meting, drie vragen.**\n\n"
            "`verzamelen` haalt reddit + tiktok op, rekent reeksen (volume, snelheid, "
            "versnelling), vangt uitschieters en extrapoleert. De drie beelden erna zijn "
            "sorteringen van diezelfde feed — geen losse berekeningen.\n\n"
            "De forecast is een extrapolatie met een eindige horizon, geen orakel. "
            "`groeiverhouding` is piek ÷ venstergemiddelde, niet 'zo veel keer nu'."}},
        {"id": "nrun", "type": "job", "x": 330, "y": 360,
         "data": {"label": "Verzamelen + rekenen (reddit, tiktok, CLIP, forecast)", "icon": "",
                  "category": "general", "targets": ["main"], "algo": "random",
                  "plugin": "shellplug",
                  "params": {"script": trend_script(TREND_UV, "pipeline.py", "--collect",
                                                    "--collect-tiktok", "--bucket", "6h"),
                             "annotate": False}}},
    ]
    conns = [{"id": "ctm", "source": "ntrigman", "dest": "nrun"},
             {"id": "ctc", "source": "ntrigcyc", "dest": "nrun"}]

    beelden = [("nconditie", "Conditie · is de feed vers?", "conditie", 120),
               ("nnu", "Trending nu · gemeten engagement", "nu", 260),
               ("nop", "Komt op · vroeg gevangen", "stijgers", 400),
               ("ntoekomst", "Voorspeld · piek binnen de horizon", "toekomst", 540)]
    for nid, label, beeld, y in beelden:
        nodes.append({"id": nid, "type": "job", "x": 720, "y": y,
                      "data": {"label": label, "icon": "", "category": "general",
                               "targets": ["main"], "algo": "random", "plugin": "shellplug",
                               "params": {"script": trend_script("python3.12", "xy_report.py", beeld),
                                          "annotate": False}}})
        # alleen na een geslaagde run: een beeld op een mislukte cyclus is een leugen
        conns.append({"id": f"cr{nid}", "source": "nrun", "dest": nid, "condition": "success"})
        conns.append({"id": f"cj{nid}", "source": nid, "dest": "njoin", "condition": "complete"})

    nodes.append({"id": "njoin", "type": "controller", "x": 1090, "y": 360,
                  "data": {"controller": "join"}})
    nodes.append({"id": "ninzicht", "type": "job", "x": 1360, "y": 360,
                  "data": {"label": "Inzichten (lokaal model leest de cijfers)", "icon": "",
                           "category": "general", "targets": ["main"], "algo": "random",
                           "plugin": "shellplug",
                           "params": {"script": trend_script(
                               "cat data/insights_latest.md 2>/dev/null || "
                               "echo 'geen insights (ollama uit?)'"), "annotate": True}}})
    conns.append({"id": "cs", "source": "njoin", "dest": "ninzicht"})

    body = {"title": TREND_TITEL, "type": "workflow", "enabled": True, "category": "general",
            "targets": ["main"], "algo": "random",
            "triggers": [{"id": "ntrigman", "type": "manual", "enabled": True},
                         {"id": "ntrigcyc", "type": "schedule", "enabled": True,
                          "hours": [2, 8, 14, 20], "minutes": [40],
                          "timezone": "Europe/Amsterdam"}],
            "workflow": {"nodes": nodes, "connections": conns},
            "limits": [{"type": "time", "enabled": True, "duration": 3600}]}
    if TREND_TITEL in er_al:
        api(cfg, "delete_event", {"id": er_al[TREND_TITEL]["id"]})
    d = api(cfg, "create_event", body)
    print(f"(her)aangemaakt: {TREND_TITEL} ({len(nodes)} knopen) {d.get('id','')}")


def main():
    _canonieke_checkout()
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
    workflow(cfg, bestaande(cfg))
    stroom_workflow(cfg, bestaande(cfg))
    trend_workflow(cfg, bestaande(cfg))


if __name__ == "__main__":
    main()
