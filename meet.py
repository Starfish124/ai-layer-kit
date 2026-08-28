"""Meet een AI-laag: lagen, grenzen, tests en ketens — gemeten, nooit opgeschreven.

Een AI-laag om een Microsoft-omgeving heen leeft al snel in drie repo's: het
platform (identiteit, audit, gate), de systemen zelf, en een herbruikbare
governance-laag. Nergens staat dan de kaart: welke laag is gebouwd, welk systeem
leest wat met welke permissie, waar staat de data, wat verlaat de tenant. Die
kaart tekent niemand met de hand, want een getekende kaart is binnen een week
gelogen. Dit bestand **meet** hem.

Eén `layers.json` per project, in de repo van het project — niet hier. De kit
kent geen klantdata en weigert paden die ernaar zouden kunnen wijzen.

Alles hier geeft platte dicts terug. De pagina (`controlroom.py`) rekent niets;
elke lamp, elk vinkje en elk citaat komt uit deze functies.

    python3.12 meet.py ~/durabo-platform/layers.json          # JSON
    python3.12 meet.py ~/durabo-platform/layers.json --run    # met tests
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

# Dezelfde vijf woorden als stride-durabo/systems.py, zodat de kleuren kloppen.
LAMPEN = ("niet gebouwd", "gebouwd, ongetest", "getest", "groen", "rood")

# Graph-permissies zoals ze in Entra-scripts voorkomen. De regex vangt ook wat
# er níet in de manifest staat — dat is precies het punt.
PERMISSIE = re.compile(r"\b(?:Mail|MailboxSettings|Files|Sites|User|Directory|"
                       r"Calendars|Contacts|Chat|ChannelMessage)\.[A-Za-z.]+\b")
SCHRIJFWERKWOORD = re.compile(r'"(?:POST|PATCH|PUT|DELETE)"')
NETWERK = {"urllib.request", "http.client"}
ADR_KOP = re.compile(r"^##\s+(ADR-\d+)\s*[—:-]?\s*(.*)$")


# ── manifest ──────────────────────────────────────────────────────────────────

def laad(pad):
    """Leest layers.json en weigert wat naar klantdata zou kunnen wijzen."""
    pad = Path(pad).expanduser()
    m = json.loads(pad.read_text(encoding="utf-8"))
    repos = {}
    for naam, p in m["repos"].items():
        p = Path(p).expanduser()
        assert p.is_dir(), f"repo '{naam}' bestaat niet: {p}"
        repos[naam] = p
    for laag in m.get("lagen", []):
        for rel in laag.get("bewijs", []) + laag.get("tests", []):
            assert not Path(rel).is_absolute(), \
                f"laag {laag['nr']}: '{rel}' is absoluut — bewijs is relatief aan de repo"
    m["repos"] = repos
    return m


# ── lagen ─────────────────────────────────────────────────────────────────────

def _test_draait(repo, test):
    r = subprocess.run([sys.executable, test], cwd=repo, capture_output=True, text=True)
    staart = (r.stdout.strip().splitlines() or r.stderr.strip().splitlines() or [""])[-1]
    return r.returncode == 0, staart


def _lamp(gebouwd, getest, groen):
    """Eén woord dat drie lampjes samenvat — overgenomen uit systems.py."""
    if not gebouwd:
        return "niet gebouwd"
    if not getest:
        return "gebouwd, ongetest"
    if groen is None:
        return "getest"
    return "groen" if groen else "rood"


def laag_status(laag, repos, run_tests=False):
    repo = repos[laag["repo"]]
    bewijs = [{"pad": b, "aanwezig": (repo / b).exists()} for b in laag.get("bewijs", [])]
    tests = [{"pad": t, "aanwezig": (repo / t).exists()} for t in laag.get("tests", [])]
    gebouwd = bool(bewijs) and all(b["aanwezig"] for b in bewijs)
    getest = bool(tests) and all(t["aanwezig"] for t in tests)
    groen, uitslagen = None, []
    if run_tests and gebouwd and getest:
        for t in tests:
            ok, staart = _test_draait(repo, t["pad"])
            uitslagen.append({"pad": t["pad"], "groen": ok, "laatste_regel": staart})
        groen = all(u["groen"] for u in uitslagen)
    return {**laag, "repo": laag["repo"], "bewijs": bewijs, "tests": tests,
            "gebouwd": gebouwd, "getest": getest, "groen": groen,
            "uitslagen": uitslagen, "lamp": _lamp(gebouwd, getest, groen)}


# ── grenzen ───────────────────────────────────────────────────────────────────

def _imports(pad):
    """Alle modulenamen die een bestand importeert — zelfde vorm als graph.py."""
    boom = ast.parse(pad.read_text(encoding="utf-8"))
    uit = set()
    for knoop in ast.walk(boom):
        if isinstance(knoop, ast.Import):
            uit.update(a.name for a in knoop.names)
        elif isinstance(knoop, ast.ImportFrom) and knoop.module:
            uit.add(knoop.module)
    return uit


def permissies_in_code(repo):
    """Welke Graph-permissies staan er letterlijk in de Entra-scripts van een repo."""
    gevonden = {}
    entra = repo / "entra"
    if not entra.is_dir():
        return gevonden
    for pad in sorted(entra.rglob("*")):
        if pad.suffix in (".sh", ".ps1", ".json") and pad.is_file():
            for p in PERMISSIE.findall(pad.read_text(encoding="utf-8", errors="replace")):
                gevonden.setdefault(p, str(pad.relative_to(repo)))
    return gevonden


def vreemde_permissies(repos, toegestaan):
    """Permissies in Entra-scripts die geen enkel systeem claimt — per repo, één keer.

    Dit is bewust geen controle per systeem: een permissie die bij niemand hoort
    is precies de permissie die je niet wilt, en die zou anders op élke kaart in
    die repo rood staan, ook op systemen die nog geen code hebben.
    """
    uit = []
    for naam, repo in repos.items():
        for p, pad in sorted(permissies_in_code(repo).items()):
            if p not in toegestaan:
                uit.append({"repo": naam, "permissie": p, "bestand": pad})
    return uit


def grens_status(systeem, repos):
    """Twee controles op de code van één systeem, elk met het bewijs erbij als hij faalt."""
    repo = repos[systeem["repo"]]
    module = repo / f"{systeem['module']}.py"
    gebouwd = module.exists()
    controles = {}

    if gebouwd:
        imports = _imports(module)
        fout = sorted(imports & set(systeem.get("verboden_imports", [])))
        controles["imports"] = {"ok": not fout, "bewijs": ", ".join(fout)}

        if systeem.get("schrijft") is False:
            # ponytail: string-grep op werkwoorden naast een netwerk-import; een
            # call-graph komt pas als een systeem legitiem ergens naartoe schrijft.
            tekst = module.read_text(encoding="utf-8")
            werkwoorden = sorted(set(SCHRIJFWERKWOORD.findall(tekst)))
            fout = bool(imports & NETWERK) and bool(werkwoorden)
            controles["schrijft_niet"] = {"ok": not fout,
                                          "bewijs": ", ".join(werkwoorden) if fout else ""}
    else:
        controles["imports"] = {"ok": None, "bewijs": "nog geen code"}
        if systeem.get("schrijft") is False:
            controles["schrijft_niet"] = {"ok": None, "bewijs": "nog geen code"}

    alles_ok = all(c["ok"] is not False for c in controles.values())
    return {**systeem, "gebouwd": gebouwd, "controles": controles, "ok": alles_ok}


# ── tests en ketens ───────────────────────────────────────────────────────────

def tests_overal(repos, run=True):
    uit = []
    for naam, repo in repos.items():
        for pad in sorted(repo.glob("test_*.py")):
            rij = {"repo": naam, "bestand": pad.name, "groen": None, "laatste_regel": ""}
            if run:
                rij["groen"], rij["laatste_regel"] = _test_draait(repo, pad.name)
            uit.append(rij)
    return uit


def audit_status(audit, repos):
    repo = repos[audit["repo"]]
    try:
        r = subprocess.run(audit["cmd"], cwd=repo, capture_output=True, text=True, timeout=60)
        staart = (r.stdout.strip().splitlines() or r.stderr.strip().splitlines() or [""])[-1]
        return {**audit, "ok": r.returncode == 0, "uitvoer": staart}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {**audit, "ok": False, "uitvoer": str(e)}


# ── beslissingen ──────────────────────────────────────────────────────────────

def beslissingen(spec, repos):
    """De ADR-koppen uit ARCHITECTURE.md. Geen bestand = rood, niet leeg."""
    pad = repos[spec["repo"]] / spec["bestand"]
    if not pad.exists():
        return {"aanwezig": False, "pad": str(pad), "lijst": []}
    lijst, huidige = [], None
    for regel in pad.read_text(encoding="utf-8").splitlines():
        m = ADR_KOP.match(regel)
        if m:
            huidige = {"nr": m[1], "titel": m[2].strip(), "eerste_regel": ""}
            lijst.append(huidige)
        elif huidige and regel.strip() and not huidige["eerste_regel"]:
            huidige["eerste_regel"] = regel.strip()
    return {"aanwezig": True, "pad": str(pad), "lijst": lijst}


# ── alles ─────────────────────────────────────────────────────────────────────

def meet(m, run_tests=False):
    repos = m["repos"]
    toegestaan = {p for s in m.get("systemen", []) for p in s.get("permissies", [])}
    lagen = [laag_status(l, repos, run_tests) for l in m.get("lagen", [])]
    systemen = [grens_status(s, repos) for s in m.get("systemen", [])]
    vreemd = vreemde_permissies(repos, toegestaan)
    tests = tests_overal(repos, run=run_tests)
    audits = [audit_status(a, repos) for a in m.get("audits", [])]
    adrs = beslissingen(m["beslissingen"], repos) if "beslissingen" in m else \
        {"aanwezig": False, "pad": "", "lijst": []}
    return {
        "project": m.get("project", ""),
        "tenant_doel": m.get("tenant_doel", ""),
        "repos": {k: str(v) for k, v in repos.items()},
        "lagen": lagen, "systemen": systemen, "vreemde_permissies": vreemd,
        "permissies_geclaimd": sorted(toegestaan), "tests": tests,
        "audits": audits, "beslissingen": adrs,
        "samenvatting": {
            "lagen_gebouwd": sum(1 for l in lagen if l["gebouwd"]),
            "lagen_totaal": len(lagen),
            "systemen_gebouwd": sum(1 for s in systemen if s["gebouwd"]),
            "systemen_totaal": len(systemen),
            "grenzen_rood": sum(1 for s in systemen if not s["ok"]) + len(vreemd),
            "tests_groen": sum(1 for t in tests if t["groen"]),
            "tests_rood": sum(1 for t in tests if t["groen"] is False),
            "tests_totaal": len(tests),
            "ketens_intact": all(a["ok"] for a in audits) if audits else None,
            "beslissingen": len(adrs["lijst"]),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(json.dumps(meet(laad(sys.argv[1]), "--run" in sys.argv),
                     ensure_ascii=False, indent=2))
