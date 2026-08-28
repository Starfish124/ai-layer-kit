"""Een nepproject met geplante fouten — allemaal gevonden, met het bewijs erbij.

De fout die telt is niet een gemiste lamp maar een groene die rood had moeten
zijn: een systeem dat `smtplib` importeert en toch "schrijft nergens" krijgt.

    python3.12 test_meet.py
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import meet

TMP = Path(tempfile.mkdtemp(prefix="ai-layer-kit-"))


def _schrijf(rel, tekst):
    p = TMP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tekst, encoding="utf-8")
    return p


def _nepproject():
    _schrijf("repo/ok.py", "import json\n")
    _schrijf("repo/bad.py", "import smtplib\nimport urllib.request\nx = \"POST\"\n")
    _schrijf("repo/test_ok.py", "print('ok: alles goed')\n")
    _schrijf("repo/test_bad.py", "import sys\nprint('kapot: hier gaat het mis')\nsys.exit(1)\n")
    _schrijf("repo/entra/x.ps1", "Add-Permission Mail.Read\nAdd-Permission Mail.ReadWrite\n")
    _schrijf("repo/ARCHITECTURE.md",
             "# Beslissingen\n\n## ADR-001 — Eerste\n\nWaarom de eerste.\n\n## ADR-002: Tweede\n\nWaarom de tweede.\n")
    manifest = {
        "project": "Nep", "tenant_doel": "test",
        "repos": {"r": str(TMP / "repo")},
        "lagen": [
            {"nr": 1, "naam": "Gebouwd en groen", "repo": "r", "bewijs": ["ok.py"], "tests": ["test_ok.py"]},
            {"nr": 2, "naam": "Gebouwd en rood", "repo": "r", "bewijs": ["bad.py"], "tests": ["test_bad.py"]},
            {"nr": 3, "naam": "Gebouwd, ongetest", "repo": "r", "bewijs": ["ok.py"], "tests": []},
            {"nr": 4, "naam": "Niet gebouwd", "repo": "r", "bewijs": ["nee.py"], "tests": []},
        ],
        "systemen": [
            {"nr": 1, "naam": "Braaf", "repo": "r", "module": "ok", "permissies": ["Mail.Read"],
             "schrijft": False, "verboden_imports": ["smtplib"]},
            {"nr": 2, "naam": "Stout", "repo": "r", "module": "bad", "permissies": [],
             "schrijft": False, "verboden_imports": ["smtplib"]},
            {"nr": 3, "naam": "Toekomst", "repo": "r", "module": "nog_niet", "permissies": [],
             "schrijft": False, "verboden_imports": ["smtplib"]},
        ],
        "audits": [
            {"naam": "heel", "repo": "r", "cmd": ["python3.12", "-c", "print('intact')"]},
            {"naam": "kapot", "repo": "r", "cmd": ["python3.12", "-c", "import sys; print('breuk op 3'); sys.exit(1)"]},
        ],
        "beslissingen": {"repo": "r", "bestand": "ARCHITECTURE.md"},
    }
    pad = _schrijf("layers.json", json.dumps(manifest))
    return pad, manifest


PAD, MANIFEST = _nepproject()
M = meet.meet(meet.laad(PAD), run_tests=True)
LAGEN = {l["nr"]: l for l in M["lagen"]}
SYS = {s["nr"]: s for s in M["systemen"]}


def test_lampen_zijn_de_vijf_woorden_van_systems():
    """Kleurcontract met stride-durabo/systems.py: zelfde woorden, zelfde kleuren."""
    for l in M["lagen"]:
        assert l["lamp"] in meet.LAMPEN, l["lamp"]
    assert LAGEN[1]["lamp"] == "groen"
    assert LAGEN[2]["lamp"] == "rood"
    assert LAGEN[3]["lamp"] == "gebouwd, ongetest"
    assert LAGEN[4]["lamp"] == "niet gebouwd"


def test_een_rode_laag_laat_de_laatste_regel_zien():
    u = LAGEN[2]["uitslagen"][0]
    assert u["groen"] is False and "hier gaat het mis" in u["laatste_regel"], u


def test_verboden_import_wordt_gevonden_en_geciteerd():
    c = SYS[2]["controles"]["imports"]
    assert c["ok"] is False and c["bewijs"] == "smtplib", c
    assert SYS[1]["controles"]["imports"]["ok"] is True
    assert SYS[2]["ok"] is False and SYS[1]["ok"] is True


def test_schrijfwerkwoord_naast_netwerk_import_is_rood():
    c = SYS[2]["controles"]["schrijft_niet"]
    assert c["ok"] is False and '"POST"' in c["bewijs"], c
    assert SYS[1]["controles"]["schrijft_niet"]["ok"] is True


def test_vreemde_permissie_in_script_wordt_een_keer_gemeld_met_bestand():
    """Mail.Read is geclaimd door systeem 1; Mail.ReadWrite door niemand — en dat
    staat één keer op repo-niveau, niet op elke kaart in die repo."""
    v = M["vreemde_permissies"]
    assert v == [{"repo": "r", "permissie": "Mail.ReadWrite", "bestand": "entra/x.ps1"}], v
    assert M["permissies_geclaimd"] == ["Mail.Read"]
    assert "permissies" not in SYS[1]["controles"], "permissies horen niet op een kaart"


def test_een_ongebouwd_systeem_heeft_een_grens_maar_geen_oordeel():
    s = SYS[3]
    assert s["gebouwd"] is False
    assert s["controles"]["imports"]["ok"] is None
    assert s["ok"] is True, "een ongebouwd systeem mag niet rood zijn"


def test_tests_overal_met_laatste_regel():
    per = {t["bestand"]: t for t in M["tests"]}
    assert per["test_ok.py"]["groen"] is True and "alles goed" in per["test_ok.py"]["laatste_regel"]
    assert per["test_bad.py"]["groen"] is False and "mis" in per["test_bad.py"]["laatste_regel"]


def test_kapotte_keten_is_gebroken_en_niet_afwezig():
    per = {a["naam"]: a for a in M["audits"]}
    assert per["heel"]["ok"] is True and per["heel"]["uitvoer"] == "intact"
    assert per["kapot"]["ok"] is False and "breuk op 3" in per["kapot"]["uitvoer"]
    assert M["samenvatting"]["ketens_intact"] is False


def test_beslissingen_worden_gelezen_in_beide_kopvormen():
    lijst = M["beslissingen"]["lijst"]
    assert [a["nr"] for a in lijst] == ["ADR-001", "ADR-002"]
    assert lijst[0]["titel"] == "Eerste" and lijst[1]["titel"] == "Tweede"
    assert lijst[0]["eerste_regel"] == "Waarom de eerste."


def test_ontbrekend_beslissingenbestand_is_rood_niet_leeg():
    b = meet.beslissingen({"repo": "r", "bestand": "weg.md"}, meet.laad(PAD)["repos"])
    assert b["aanwezig"] is False and b["lijst"] == []


def test_absoluut_bewijspad_wordt_geweigerd():
    """Bewijs is relatief aan de repo. Een absoluut pad kan naar klantdata wijzen."""
    m = dict(MANIFEST)
    m["lagen"] = [{"nr": 9, "naam": "x", "repo": "r", "bewijs": ["/etc/passwd"], "tests": []}]
    pad = _schrijf("fout.json", json.dumps(m))
    try:
        meet.laad(pad)
    except AssertionError as e:
        assert "absoluut" in str(e)
    else:
        raise AssertionError("absoluut pad geaccepteerd")


def test_samenvatting_telt_wat_de_pagina_toont():
    s = M["samenvatting"]
    assert s["lagen_gebouwd"] == 3 and s["lagen_totaal"] == 4
    assert s["systemen_gebouwd"] == 2 and s["systemen_totaal"] == 3
    assert s["grenzen_rood"] == 2   # Stout (import) + één vreemde permissie in de repo
    assert s["tests_groen"] == 1 and s["tests_rood"] == 1 and s["tests_totaal"] == 2
    assert s["beslissingen"] == 2


if __name__ == "__main__":
    try:
        for naam, fn in sorted(globals().items()):
            if naam.startswith("test_"):
                fn()
                print(f"  ok  {naam}")
        print("meet: elke lamp is gemeten, elke rode heeft zijn bewijs bij zich")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
