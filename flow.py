"""De stroom: bronnen → systemen → uitvoer, en binnen een systeem functie → functie.

Een werkstroom-canvas zoals n8n of Power Automate, maar elk blok is echte code.
Niets hier is met de hand geplaatst: het overzicht komt uit `layers.json`, de
binnenkant van een systeem uit `ast`. Een functie is een knoop; een pijl van A
naar B betekent: A roept B aan, dus data stroomt van B's uitkomst naar A. De
regeltabellen (hoofdletter-constanten als DOCUMENTEN, MAILREGELS) zijn ook
knopen, want dat is waar de regels staan die de functies uitvoeren.

Lagen zoals in stride-durabo/graph.py: wie niets aanroept staat links, wie het
meest aanroept rechts. Zo leest de kaart als de data zelf: bron → bewerking →
uitkomst.

    python3.12 flow.py ~/durabo-platform/layers.json             # overzicht
    python3.12 flow.py ~/durabo-platform/layers.json post        # binnen één systeem
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import meet


# ── overzicht: bronnen → systemen → uitvoer ────────────────────────────────────

def overzicht(m):
    """Uit layers.json: elke bron één knoop, elk systeem één knoop, uitvoer als het bestaat."""
    repos = m["repos"]
    nodes, edges = [], []
    bronnen = {}
    for s in m.get("systemen", []):
        for b in s.get("bronnen", []):
            bronnen.setdefault(b, f"bron:{len(bronnen)}")
    for b, bid in bronnen.items():
        nodes.append({"id": bid, "soort": "bron", "naam": b, "laag": 0, "doc": ""})

    for i, s in enumerate(m.get("systemen", [])):
        pad = repos[s["repo"]] / f"{s['module']}.py"
        gebouwd = pad.exists()
        boom = ast.parse(pad.read_text(encoding="utf-8")) if gebouwd else None
        sid = f"sys:{s['module']}"
        nodes.append({
            "id": sid, "soort": "systeem", "naam": f"{s['nr']} · {s['naam']}",
            "module": s["module"], "gebouwd": gebouwd, "laag": 1,
            "doc": ", ".join(s.get("permissies", [])) or "geen permissie",
            "residentie": s.get("residentie", ""), "verlaat_tenant": s.get("verlaat_tenant", ""),
            "bronnen": s.get("bronnen", []),
            # het gemeten datacontract: welke velden leest deze code uit zijn invoer
            "velden": velden(boom) if gebouwd else [],
        })
        for b in s.get("bronnen", []):
            edges.append([bronnen[b], sid])
        if gebouwd:
            uid = f"uit:{s['module']}"
            uitk = uitkomsten(boom)
            nodes.append({"id": uid, "soort": "uitvoer", "naam": "pagina + JSON",
                          "laag": 2, "doc": " · ".join(uitk) or s.get("verlaat_tenant", ""),
                          "uitkomsten": uitk, "verlaat_tenant": s.get("verlaat_tenant", "")})
            edges.append([sid, uid])
    _rijen(nodes)
    return {"titel": m.get("project", ""), "niveau": "overzicht",
            "nodes": nodes, "edges": edges}


def velden(boom):
    """De letterlijke sleutels die de code uit zijn invoer leest: `x.get("veld")`.

    Er zijn hier geen schema's — de motoren werken op platte dicts, bewust. Dit is
    het contract dat wél bestaat, en het is gemeten in plaats van opgeschreven.
    """
    uit = set()
    for k in ast.walk(boom):
        if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute) \
                and k.func.attr == "get" and k.args \
                and isinstance(k.args[0], ast.Constant) and isinstance(k.args[0].value, str):
            uit.add(k.args[0].value)
    return sorted(uit)


def uitkomsten(boom):
    """`UITKOMSTEN = ("…", "…")` bovenin een module: de namen die het systeem geeft
    aan wat het niet kon beslissen. Die horen op het uitvoerblok, want dat is waar
    een fout stroomopwaarts zichtbaar wordt."""
    for k in boom.body:
        if isinstance(k, ast.Assign) and len(k.targets) == 1 \
                and isinstance(k.targets[0], ast.Name) and k.targets[0].id == "UITKOMSTEN":
            try:
                waarde = ast.literal_eval(k.value)
            except ValueError:
                return []
            return [str(v) for v in waarde] if isinstance(waarde, (tuple, list)) else []
    return []


# ── binnenkant: functie → functie ─────────────────────────────────────────────

def _namen_in(knoop):
    return {n.id for n in ast.walk(knoop) if isinstance(n, ast.Name)}


DEKKING = """
import json, runpy, sys, trace
t = trace.Trace(count=1, trace=0)
try:
    t.runfunc(runpy.run_path, sys.argv[1], run_name="__main__")
except SystemExit:
    pass
print(json.dumps(sorted({l for (f, l) in t.results().counts
                         if f.rsplit("/", 1)[-1] == sys.argv[2]})))
"""


def dekking(module_pad, test_pad):
    """Welke regels van de module raakt zijn test. stdlib `trace`, in een subprocess."""
    r = subprocess.run([sys.executable, "-c", DEKKING, test_pad.name, module_pad.name],
                       cwd=module_pad.parent, capture_output=True, text=True, timeout=180)
    try:
        return set(json.loads(r.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return None


def functies(module_pad, run=False):
    """Top-level functies en hoofdletter-constanten van één bestand, met hun code."""
    bron = Path(module_pad).read_text(encoding="utf-8")
    boom = ast.parse(bron)
    nodes, gebruikt = [], {}

    for k in boom.body:
        if isinstance(k, ast.FunctionDef):
            # De def-regel en de docstring 'draaien' al bij import; dekking telt
            # pas vanaf de eerste echte regel van het lijf.
            lijf = k.body[1:] if ast.get_docstring(k) else k.body
            nodes.append({"id": k.name, "soort": "functie", "naam": k.name,
                          "doc": (ast.get_docstring(k) or "").splitlines()[0]
                          if ast.get_docstring(k) else "",
                          "regels": [k.lineno, k.end_lineno],
                          "lijf": lijf[0].lineno if lijf else k.end_lineno + 1,
                          "code": ast.get_source_segment(bron, k)})
            gebruikt[k.name] = _namen_in(k)
        elif isinstance(k, ast.Assign) and len(k.targets) == 1 \
                and isinstance(k.targets[0], ast.Name) and k.targets[0].id.isupper():
            naam = k.targets[0].id
            nodes.append({"id": naam, "soort": "data", "naam": naam, "doc": "regeltabel",
                          "regels": [k.lineno, k.end_lineno],
                          "code": ast.get_source_segment(bron, k)})

    ids = {n["id"] for n in nodes}
    edges = [[f, g] for f, ns in gebruikt.items() for g in sorted(ns & ids) if g != f]
    _lagen(nodes, edges)
    _rijen(nodes)

    # Met ?run=1: welke functies raakt de test van deze module echt. Een functie
    # die geen test aanraakt is niet fout, maar je wilt het wél zien.
    test_pad = Path(module_pad).with_name(f"test_{Path(module_pad).name}")
    geraakt = dekking(Path(module_pad), test_pad) if run and test_pad.exists() else None
    if geraakt is not None:
        for n in nodes:
            if n["soort"] == "functie":
                a, b = n["lijf"], n["regels"][1]
                n["geraakt"] = any(a <= l <= b for l in geraakt)
    return {"titel": Path(module_pad).name, "niveau": "systeem",
            "nodes": nodes, "edges": edges, "dekking": geraakt is not None}


def _lagen(nodes, edges):
    """Laag 0 = roept niets van ons aan. Daarboven: één hoger dan wat je aanroept.
    Begrensd op het aantal knopen, zodat recursie of een cyclus niet blijft hangen."""
    per = {n["id"]: n for n in nodes}
    deps = {n["id"]: [] for n in nodes}
    for a, b in edges:
        deps[a].append(b)
    for n in nodes:
        n["laag"] = 0
    for _ in range(len(nodes)):
        moved = False
        for n in nodes:
            want = max((per[d]["laag"] + 1 for d in deps[n["id"]]), default=0)
            if want > n["laag"]:
                n["laag"], moved = want, True
        if not moved:
            break


def _rijen(nodes):
    """Rij binnen een kolom = volgorde in het bestand of de manifest. Deterministisch."""
    tel = {}
    for n in nodes:
        n["rij"] = tel.get(n["laag"], 0)
        tel[n["laag"]] = n["rij"] + 1


def stroom(m, module=None, run=False):
    if not module:
        return overzicht(m)
    for s in m.get("systemen", []):
        if s["module"] == module:
            pad = m["repos"][s["repo"]] / f"{module}.py"
            if not pad.exists():
                return {"titel": module, "niveau": "systeem", "nodes": [], "edges": [],
                        "fout": "nog niet gebouwd"}
            return functies(pad, run)
    return {"titel": module, "niveau": "systeem", "nodes": [], "edges": [],
            "fout": "onbekend systeem"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    m = meet.laad(sys.argv[1])
    print(json.dumps(stroom(m, sys.argv[2] if len(sys.argv) > 2 else None, "--run" in sys.argv),
                     ensure_ascii=False, indent=2))
