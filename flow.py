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
        gebouwd = (repos[s["repo"]] / f"{s['module']}.py").exists()
        sid = f"sys:{s['module']}"
        nodes.append({
            "id": sid, "soort": "systeem", "naam": f"{s['nr']} · {s['naam']}",
            "module": s["module"], "gebouwd": gebouwd, "laag": 1,
            "doc": ", ".join(s.get("permissies", [])) or "geen permissie",
            "residentie": s.get("residentie", ""), "verlaat_tenant": s.get("verlaat_tenant", ""),
        })
        for b in s.get("bronnen", []):
            edges.append([bronnen[b], sid])
        if gebouwd:
            uid = f"uit:{s['module']}"
            nodes.append({"id": uid, "soort": "uitvoer", "naam": "pagina + JSON",
                          "laag": 2, "doc": s.get("verlaat_tenant", "")})
            edges.append([sid, uid])
    _rijen(nodes)
    return {"titel": m.get("project", ""), "niveau": "overzicht",
            "nodes": nodes, "edges": edges}


# ── binnenkant: functie → functie ─────────────────────────────────────────────

def _namen_in(knoop):
    return {n.id for n in ast.walk(knoop) if isinstance(n, ast.Name)}


def functies(module_pad):
    """Top-level functies en hoofdletter-constanten van één bestand, met hun code."""
    bron = Path(module_pad).read_text(encoding="utf-8")
    boom = ast.parse(bron)
    nodes, gebruikt = [], {}

    for k in boom.body:
        if isinstance(k, ast.FunctionDef):
            nodes.append({"id": k.name, "soort": "functie", "naam": k.name,
                          "doc": (ast.get_docstring(k) or "").splitlines()[0]
                          if ast.get_docstring(k) else "",
                          "regels": [k.lineno, k.end_lineno],
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
    return {"titel": Path(module_pad).name, "niveau": "systeem",
            "nodes": nodes, "edges": edges}


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


def stroom(m, module=None):
    if not module:
        return overzicht(m)
    for s in m.get("systemen", []):
        if s["module"] == module:
            pad = m["repos"][s["repo"]] / f"{module}.py"
            if not pad.exists():
                return {"titel": module, "niveau": "systeem", "nodes": [], "edges": [],
                        "fout": "nog niet gebouwd"}
            return functies(pad)
    return {"titel": module, "niveau": "systeem", "nodes": [], "edges": [],
            "fout": "onbekend systeem"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    m = meet.laad(sys.argv[1])
    print(json.dumps(stroom(m, sys.argv[2] if len(sys.argv) > 2 else None),
                     ensure_ascii=False, indent=2))
