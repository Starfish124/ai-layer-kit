"""De bewaking moet rood worden. Een controle die nooit rood is, is geen controle.

Elke plant hier is een echte fout uit de praktijk: een dienst op 0.0.0.0 (dat is
28 aug een halve dag zo geweest), een poort op Funnel, een sleutelbestand dat
wereldleesbaar is, en een schrijfpoort die te veel of te weinig weigert.

    python3.12 test_bewaking.py
"""

import json
import shutil
import tempfile
from pathlib import Path

import bewaking

TMP = Path(tempfile.mkdtemp(prefix="bewaking-"))

LSOF_GOED = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
node 1 u 1 IPv4 0x1 0t0 TCP 127.0.0.1:5522 (LISTEN)
Python 2 u 2 IPv4 0x2 0t0 TCP 127.0.0.1:7415 (LISTEN)
"""
LSOF_FOUT = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
node 1 u 1 IPv4 0x1 0t0 TCP *:5522 (LISTEN)
Python 2 u 2 IPv4 0x2 0t0 TCP 192.168.1.9:7415 (LISTEN)
"""
FUNNEL = """# Funnel on:
https://mac-mini.ts.net (Funnel on)
|-- /    proxy http://127.0.0.1:3000
|-- /x   proxy http://127.0.0.1:7415

https://mac-mini.ts.net:8446 (tailnet only)
|-- / proxy http://127.0.0.1:5522
"""

POORTEN = {"xyops": 5522, "controlekamer": 7415}


def _nep_draai(uitvoer, code=0):
    return lambda cmd, **kw: (code, uitvoer)


def test_dienst_op_alle_interfaces_wordt_rood():
    """De regressie van 28 augustus: 0.0.0.0 en een LAN-adres, allebei gevonden."""
    bewaking._draai = _nep_draai(LSOF_FOUT)
    r = bewaking.alleen_lokaal(POORTEN)
    assert r["ok"] is False, r
    assert "xyops luistert op *:5522" in r["bewijs"], r["bewijs"]
    assert "controlekamer luistert op 192.168.1.9:7415" in r["bewijs"], r["bewijs"]


def test_alles_op_loopback_is_groen():
    bewaking._draai = _nep_draai(LSOF_GOED)
    assert bewaking.alleen_lokaal(POORTEN)["ok"] is True


def test_funnel_telt_alleen_het_funnel_blok():
    """7415 staat publiek (rood), 5522 staat alleen op het tailnet (mag)."""
    bewaking._draai = _nep_draai(FUNNEL)
    r = bewaking.niet_op_funnel(POORTEN)
    assert r["ok"] is False and "7415" in r["bewijs"], r
    assert "5522" not in r["bewijs"], "een tailnet-only poort mag geen alarm geven"
    assert r["publiek"] == [3000, 7415]


def test_wereldleesbare_sleutel_wordt_rood():
    goed, fout = TMP / "goed.json", TMP / "fout.json"
    goed.write_text("{}"); goed.chmod(0o600)
    fout.write_text("{}"); fout.chmod(0o644)
    bewaking._draai = _nep_draai("", code=1)          # niet in git
    assert bewaking.sleutels_afgeschermd([str(goed)])["ok"] is True
    r = bewaking.sleutels_afgeschermd([str(fout)])
    assert r["ok"] is False and "644" in r["bewijs"], r


def test_sleutel_in_git_wordt_rood():
    p = TMP / "in_git.json"; p.write_text("{}"); p.chmod(0o600)
    bewaking._draai = _nep_draai("", code=0)          # git kent het bestand
    r = bewaking.sleutels_afgeschermd([str(p)])
    assert r["ok"] is False and "staat in git" in r["bewijs"], r


def test_poort_die_niets_weigert_wordt_rood():
    """Een poort die op alles '0' zegt laat een productie-schrijfactie door."""
    (TMP / "config.json").write_text(json.dumps({"prod_markers": ["PROD-MARKER"]}))
    bewaking._draai = _nep_draai("0\n")
    r = bewaking.poort_weigert(TMP)
    assert r["ok"] is False and "schrijven naar productie" in r["bewijs"], r


def test_poort_die_alles_weigert_wordt_ook_rood():
    """Alles weigeren is net zo stuk: dan zet iemand de poort uit."""
    (TMP / "config.json").write_text(json.dumps({"prod_markers": ["PROD-MARKER"]}))
    bewaking._draai = _nep_draai("1\n")
    r = bewaking.poort_weigert(TMP)
    assert r["ok"] is False, r
    assert "lezen van productie" in r["bewijs"] and "schrijven naar dev" in r["bewijs"], r["bewijs"]


def test_ontbrekend_gereedschap_is_grijs_niet_groen():
    """lsof weg = we weten het niet. Dat mag nooit als 'veilig' tellen."""
    bewaking._draai = lambda cmd, **kw: (None, "command not found")
    assert bewaking.alleen_lokaal(POORTEN)["ok"] is None
    assert bewaking.niet_op_funnel(POORTEN)["ok"] is None


if __name__ == "__main__":
    echt = bewaking._draai
    try:
        for naam, fn in sorted(globals().items()):
            if naam.startswith("test_") and callable(fn):
                bewaking._draai = echt
                fn()
                print(f"  ok  {naam}")
        print("bewaking: elke grens is aangedrukt, ook van de verkeerde kant")
    finally:
        bewaking._draai = echt
        shutil.rmtree(TMP, ignore_errors=True)
