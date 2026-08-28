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
