"""Elke knoop is echte code, elke pijl een echte aanroep, en niemand heeft iets geplaatst.

    python3.12 test_flow.py
"""

import json
import shutil
import tempfile
from pathlib import Path

import flow
import meet

TMP = Path(tempfile.mkdtemp(prefix="ai-layer-kit-flow-"))
MODULE = '''"""Nepsysteem."""
UITKOMSTEN = ("bron ontbreekt", "veld ontbreekt")
REGELS = [1, 2, 3]

def _pak(x):
    """Haalt één ding op."""
    return REGELS[x]

def vul(order):
    """Vult uit de bron."""
    order.get("klant"); order.get("artikelnummer")
    return [_pak(i) for i in order]

def werk_af(orders):
    return sorted(vul(o) for o in orders)

def los():
    return 1
'''


def _nep():
    (TMP / "repo").mkdir(parents=True, exist_ok=True)
    (TMP / "repo" / "nep.py").write_text(MODULE)
    (TMP / "repo" / "test_nep.py").write_text("import nep\nnep.werk_af([{0: 1}, {1: 2}])\nprint('ok')\n")
    manifest = {"project": "Nep", "tenant_doel": "t", "repos": {"r": str(TMP / "repo")},
                "lagen": [], "audits": [],
                "systemen": [
                    {"nr": 1, "naam": "Nep", "repo": "r", "module": "nep",
                     "bronnen": ["order", "artikelstam"], "permissies": ["Mail.Read"],
                     "residentie": "tenant", "verlaat_tenant": "niets", "schrijft": False},
                    {"nr": 2, "naam": "Later", "repo": "r", "module": "later",
                     "bronnen": ["order"], "permissies": [], "schrijft": False}]}
    (TMP / "layers.json").write_text(json.dumps(manifest))
    return meet.laad(TMP / "layers.json")


M = _nep()
O = flow.stroom(M)
F = flow.stroom(M, "nep")


def test_overzicht_deelt_bronnen_en_koppelt_ze():
    ids = {n["id"]: n for n in O["nodes"]}
    bronnen = [n for n in O["nodes"] if n["soort"] == "bron"]
    assert {b["naam"] for b in bronnen} == {"order", "artikelstam"}, "bron 'order' hoort één knoop te zijn"
    order = [b for b in bronnen if b["naam"] == "order"][0]["id"]
    assert [order, "sys:nep"] in O["edges"] and [order, "sys:later"] in O["edges"]
    assert ids["sys:nep"]["gebouwd"] is True and ids["sys:later"]["gebouwd"] is False
    assert "uit:nep" in ids and "uit:later" not in ids, "alleen een gebouwd systeem heeft uitvoer"
    assert ids["sys:nep"]["doc"] == "Mail.Read"


def test_functies_zijn_knopen_met_hun_eigen_code():
    ids = {n["id"]: n for n in F["nodes"]}
    assert set(ids) == {"UITKOMSTEN", "REGELS", "_pak", "vul", "werk_af", "los"}
    assert ids["REGELS"]["soort"] == "data" and ids["vul"]["soort"] == "functie"
    assert ids["vul"]["code"].startswith("def vul(order):") and "_pak(i)" in ids["vul"]["code"]
    assert ids["vul"]["doc"] == "Vult uit de bron."
    assert ids["_pak"]["regels"] == [5, 7]


def test_pijlen_zijn_echte_aanroepen():
    assert ["vul", "_pak"] in F["edges"]
    assert ["werk_af", "vul"] in F["edges"]
    assert ["_pak", "REGELS"] in F["edges"], "een functie die een regeltabel leest krijgt een pijl"
    assert not any(a == "los" or b == "los" for a, b in F["edges"])


def test_lagen_lopen_van_bron_naar_uitkomst():
    laag = {n["id"]: n["laag"] for n in F["nodes"]}
    assert laag["REGELS"] == 0 and laag["_pak"] == 1 and laag["vul"] == 2 and laag["werk_af"] == 3
    assert laag["los"] == 0


def test_velden_en_uitkomsten_zijn_gemeten_contracten():
    ids = {n["id"]: n for n in O["nodes"]}
    assert ids["sys:nep"]["velden"] == ["artikelnummer", "klant"], "de .get-sleutels zijn het contract"
    assert ids["sys:later"]["velden"] == []
    assert ids["uit:nep"]["uitkomsten"] == ["bron ontbreekt", "veld ontbreekt"]
    assert ids["uit:nep"]["doc"] == "bron ontbreekt · veld ontbreekt"


def test_dekking_zegt_welke_functie_de_test_raakt():
    """test_nep roept werk_af → vul → _pak; `los` raakt niemand aan."""
    d = flow.stroom(M, "nep", run=True)
    assert d["dekking"] is True
    ids = {n["id"]: n for n in d["nodes"]}
    assert ids["werk_af"]["geraakt"] and ids["vul"]["geraakt"] and ids["_pak"]["geraakt"]
    assert ids["los"]["geraakt"] is False
    assert "geraakt" not in ids["REGELS"], "regeltabellen worden altijd geraakt bij import — niets te melden"
    assert "geraakt" not in F["nodes"][0] or F["dekking"] is False, "zonder run geen dekking"


def test_niets_is_met_de_hand_geplaatst():
    for n in F["nodes"] + O["nodes"]:
        assert "x" not in n and "y" not in n, "posities horen niet in de data"
        assert "rij" in n and "laag" in n


def test_ongebouwd_en_onbekend_zeggen_dat():
    assert flow.stroom(M, "later")["fout"] == "nog niet gebouwd"
    assert flow.stroom(M, "bestaatniet")["fout"] == "onbekend systeem"


if __name__ == "__main__":
    try:
        for naam, fn in sorted(globals().items()):
            if naam.startswith("test_") and callable(fn):
                fn()
                print(f"  ok  {naam}")
        print("stroom: elk blok is code, elke pijl een aanroep, niets geplaatst")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
