"""De pagina toont alles en rekent niets.

    python3.12 test_controlroom.py
"""

import re
from pathlib import Path

import controlroom
import test_meet   # bouwt het nepproject en meet het

M = test_meet.M
H = controlroom.html(M)


def test_vier_secties_in_volgorde():
    koppen = re.findall(r"<h2>(.*?)</h2>", H)
    assert koppen == ["Lagen", "Grenzen per systeem", "Tests en ketens", "Beslissingen"], koppen


def test_elke_lamp_staat_op_de_pagina():
    for l in M["lagen"]:
        assert f'>{l["lamp"]}</span>' in H, l["lamp"]
    assert "GEBROKEN" in H, "een gebroken keten moet schreeuwen"


def test_rode_grens_citeert_het_bewijs():
    assert "“smtplib”" in H
    assert "Mail.ReadWrite in entra/x.ps1" in H


def test_sonde_is_grijs_en_tijdstip_staat_erop():
    assert "niet uitvoerbaar" in H and "Gemeten op <b>" in H


def test_check_is_een_poort_over_de_overschreven_repo():
    """Rood in scope → exit 1 met het bewijs; scope leeg → alles telt."""
    import io, contextlib
    m = dict(M); m["overrides"] = ["r"]
    uit = io.StringIO()
    with contextlib.redirect_stdout(uit):
        code = controlroom.check(m)
    assert code == 1 and "smtplib" in uit.getvalue() and "test rood: test_bad.py" in uit.getvalue()
    assert "Let op" in controlroom.html(m) and "worktree" in controlroom.html(m)


def test_xy_regel_is_geldig_en_exit_volgt_rood():
    """xyOps leest één JSON-regel; rood = exit 1, alleen tests rood = waarschuwing."""
    import json, live
    live.EVENTS = test_meet.TMP / "events.jsonl"     # niet in het echte bestand schrijven
    uit, code = controlroom.xy(M)
    assert uit["xy"] is True and code == 1
    assert json.loads(json.dumps(uit))["data"]["grenzen_rood"] == 2
    assert "smtplib" in uit["markdown"] and "test rood: test_bad.py" in uit["markdown"]
    assert uit["warning"].startswith("3 waarschuwing")   # test_bad + sonde + weg
    assert any(r[2] == "groen" for r in uit["table"]["rows"])
    assert live.EVENTS.exists() and "meting" in live.EVENTS.read_text()


def test_stroom_komt_uit_de_gebouwde_dist_en_blijft_binnen():
    assert controlroom._dist_bestand("/flow").name == "index.html"
    assert controlroom._dist_bestand("/flow/../controlroom.py") is None, "pad-ontsnapping"
    h = controlroom.stroom_html({"": {"nodes": [], "edges": [], "titel": "x"}})
    assert "window.STROOM=" in h and "<script type=\"module\">" in h
    assert re.search(r"<script[^>]+src=", h) is None and re.search(r"<link[^>]+stylesheet", h) is None, \
        "de export moet zonder server en zonder losse bestanden werken"


def test_beslissingen_op_de_pagina():
    assert "ADR-001" in H and "Eerste" in H and "Waarom de tweede." in H


def test_pagina_rekent_zelf_niets():
    """Als controlroom.py subprocess of ast aanraakt, meet de pagina zelf — en dan liegt hij."""
    bron = Path(controlroom.__file__).read_text(encoding="utf-8")
    for verboden in ("subprocess", "import ast", "ast."):
        assert verboden not in bron, f"controlroom.py bevat {verboden!r}"


def test_html_is_ontsnapt():
    m = dict(M)
    m["project"] = "<script>alert(1)</script>"
    assert "<script>" not in controlroom.html(m)


if __name__ == "__main__":
    try:
        for naam, fn in sorted(globals().items()):
            if naam.startswith("test_") and callable(fn):
                fn()
                print(f"  ok  {naam}")
        print("controlekamer: toont alles, rekent niets")
    finally:
        import shutil
        shutil.rmtree(test_meet.TMP, ignore_errors=True)
