"""De bewaking meet zichzelf: staan de grenzen die we beloofd hebben er echt?

De controlekamer meet of de *code* zich gedraagt. Dit bestand meet of de
*omgeving* zich gedraagt: luistert er niets buiten loopback, staat er niets van
ons op Funnel, zijn de sleutelbestanden afgeschermd, en weigert de schrijfpoort
echt wat hij zegt te weigeren.

Dat laatste is het punt van dit bestand. Een poort waarvan je aanneemt dat hij
dicht is, is geen poort. Hier wordt hij aangedrukt: één aanroep die geweigerd
moet worden en één die door moet, allebei elke run.

Waarom dit bestaat: op 28 augustus stond de controlekamer een halve dag op
`0.0.0.0` — bereikbaar vanaf elk netwerk waar deze Mac op zit — en niets merkte
het op. Deze controle zou dat binnen een kwartier rood hebben gezet.

    python3.12 bewaking.py ~/durabo-platform/layers.json
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import meet

LOOPBACK = ("127.0.0.1", "localhost", "[::1]", "::1")


def _draai(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


# ── 1. luistert alles alleen op loopback ──────────────────────────────────────

def alleen_lokaal(poorten):
    """Onze diensten horen op 127.0.0.1 te luisteren; van buiten komt men via het
    tailnet. Een dienst op `*` of op een LAN-adres is bereikbaar voor iedereen op
    hetzelfde wifi — en `?run=1` draait testbestanden."""
    code, uit = _draai(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
    if code is None:
        return {"ok": None, "bewijs": f"lsof niet uitvoerbaar: {uit[:80]}"}
    fout = []
    for regel in uit.splitlines()[1:]:
        velden = regel.split()
        if len(velden) < 9:
            continue
        adres = velden[8]
        host, _, poort = adres.rpartition(":")
        if not poort.isdigit() or int(poort) not in poorten.values():
            continue
        if host not in LOOPBACK:
            naam = next(k for k, v in poorten.items() if v == int(poort))
            fout.append(f"{naam} luistert op {adres}")
    return {"ok": not fout, "bewijs": "; ".join(sorted(set(fout)))}


# ── 2. niets van ons op Funnel ────────────────────────────────────────────────

def niet_op_funnel(poorten):
    """`tailscale serve` is tailnet-only; Funnel is het publieke internet. Niets
    van deze stapel hoort daarop: de runner voert code uit."""
    code, uit = _draai(["tailscale", "funnel", "status"])
    if code is None:
        return {"ok": None, "bewijs": f"tailscale niet uitvoerbaar: {uit[:80]}"}
    # `funnel status` toont ook de tailnet-only blokken. Alleen regels onder een
    # kop met "(Funnel on)" zijn publiek; blind grepnen levert vals alarm op elke
    # poort die je netjes via `serve` deelt.
    publiek, funnel_blok = set(), False
    for regel in uit.splitlines():
        kop = re.match(r"^\w+://\S+\s+\((.+)\)\s*$", regel)
        if kop:
            funnel_blok = "funnel on" in kop.group(1).lower()
            continue
        if funnel_blok and regel.lstrip().startswith("|--"):
            publiek.update(int(x) for x in re.findall(r"(?:127\.0\.0\.1|localhost):(\d+)", regel))
    fout = [f"poort {p} ({naam}) staat op Funnel — publiek internet"
            for naam, p in poorten.items() if p in publiek]
    return {"ok": not fout, "bewijs": "; ".join(fout), "publiek": sorted(publiek)}


# ── 3. sleutels afgeschermd ───────────────────────────────────────────────────

def sleutels_afgeschermd(bestanden):
    """Een sleutelbestand hoort 0600 te zijn en niet in git te staan."""
    fout = []
    for pad in bestanden:
        p = Path(pad).expanduser()
        if not p.exists():
            continue
        modus = p.stat().st_mode & 0o777
        if modus & 0o077:
            fout.append(f"{p.name} is {oct(modus)[2:]} (moet 600)")
        code, _ = _draai(["git", "ls-files", "--error-unmatch", str(p)], cwd=p.parent)
        if code == 0:
            fout.append(f"{p.name} staat in git")
    return {"ok": not fout, "bewijs": "; ".join(fout)}


# ── 4. de schrijfpoort weigert echt ───────────────────────────────────────────

PROEF = (
    "import sys, json, audit_hook as a\n"
    "p = json.loads(sys.argv[1])\n"
    "print(int(bool(a.is_write(p['tool'].split('__')[-1]) and a.touches_prod(p['args']))))\n"
)


def poort_weigert(platform_repo):
    """Twee kanten op: een schrijfaanroep naar productie moet geweigerd worden, en
    een leesaanroep moet erdoor. Een poort die alles weigert is net zo stuk als
    een poort die niets weigert — dan zet iemand hem uit.

    Dit toetst de beslissing, niet de hook-bedrading (die staat in
    `test_audit_hook.py`), en schrijft dus niets in de echte keten.
    """
    cfg_pad = platform_repo / "config.json"
    if not cfg_pad.exists():
        return {"ok": None, "bewijs": "geen config.json"}
    markers = json.loads(cfg_pad.read_text()).get("prod_markers") or []
    if not markers:
        return {"ok": None, "bewijs": "geen prod_markers ingesteld"}

    gevallen = [
        ("schrijven naar productie", {"tool": "mcp__dataverse__create_row",
                                      "args": {"url": markers[0]}}, "1"),
        ("lezen van productie", {"tool": "mcp__dataverse__read_query",
                                 "args": {"url": markers[0]}}, "0"),
        ("schrijven naar dev", {"tool": "mcp__dataverse__create_row",
                                "args": {"url": "https://dev.example.crm4.dynamics.com"}}, "0"),
    ]
    fout = []
    for naam, payload, verwacht in gevallen:
        code, uit = _draai([sys.executable, "-c", PROEF, json.dumps(payload)],
                           cwd=platform_repo)
        gekregen = (uit.strip().splitlines() or [""])[-1]
        if gekregen != verwacht:
            fout.append(f"{naam}: poort zei {gekregen or '?'}, verwacht {verwacht}")
    return {"ok": not fout, "bewijs": "; ".join(fout)}


# ── alles ─────────────────────────────────────────────────────────────────────

def meet_bewaking(m):
    poorten = m.get("poorten") or {}
    platform = m["repos"][m["beslissingen"]["repo"]] if "beslissingen" in m else None
    controles = {
        "alleen loopback": alleen_lokaal(poorten) if poorten
                           else {"ok": None, "bewijs": "geen poorten in layers.json"},
        "niet op funnel": niet_op_funnel(poorten) if poorten
                          else {"ok": None, "bewijs": "geen poorten in layers.json"},
        "sleutels afgeschermd": sleutels_afgeschermd(m.get("sleutelbestanden") or []),
        "schrijfpoort weigert": poort_weigert(platform) if platform
                                else {"ok": None, "bewijs": "geen platform-repo"},
    }
    return {"controles": controles,
            "ok": all(c["ok"] is not False for c in controles.values())}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(json.dumps(meet_bewaking(meet.laad(sys.argv[1])), ensure_ascii=False, indent=2))
