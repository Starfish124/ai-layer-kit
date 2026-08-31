"""De controlekamer: één pagina over lagen, grenzen, tests en beslissingen.

Deze pagina rekent niets. Elke lamp, elk vinkje en elk citaat komt uit
`meet.py`; hier wordt alleen HTML van gemaakt. Dat is bewust en `test_controlroom`
houdt het zo — een pagina die zelf meet, liegt op den duur.

    python3.12 controlroom.py <layers.json> --html          # naar stdout
    python3.12 controlroom.py <layers.json> --run --html    # mét tests
    python3.12 controlroom.py <layers.json> --serve         # http://127.0.0.1:7415
    python3.12 controlroom.py <layers.json> --run --export ~/Downloads   # twee losse HTML's
    python3.12 controlroom.py <layers.json> --repo systemen=$PWD --serve --port 7416
    python3.12 controlroom.py <layers.json> --repo systemen=$PWD --run --check
    python3.12 controlroom.py <layers.json> --run --xy         # één JSON-regel voor een xyOps-job
    python3.12 controlroom.py <layers.json> --systeem post     # één systeem, één xyOps-knoop
    python3.12 controlroom.py <layers.json> --bewaking         # loopback, funnel, sleutels, poort
    python3.12 controlroom.py <layers.json> --tally grenzen_rood   # één getal voor een xyOps-monitor
    curl -N http://127.0.0.1:7415/events                          # de live feitenstroom (SSE)
        # meet een worktree i.p.v. de hoofdrepo; exit 1 als daar iets rood is (Vibe Kanban-poort)
"""

import json
import pathlib
import re
import sys
from html import escape as esc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import bewaking
import flow
import live
import meet
import waarneming

PORT = 7415   # vrij van 7350/7360/7411/7455/8420/8765/8766

LAMP_KLEUR = {
    "groen": ("var(--good)", "#e6f3ea"),
    "rood": ("var(--danger)", "#fbeae9"),
    "getest": ("var(--teal)", "var(--teal-tint)"),
    "gebouwd, ongetest": ("var(--warn)", "var(--warn-tint)"),
    "niet gebouwd": ("var(--faint)", "var(--paper)"),
}


def _pil(tekst, lamp):
    rand, vul = LAMP_KLEUR[lamp]
    return (f'<span class="pil" style="border-color:{rand};background:{vul};'
            f'color:{rand}">{esc(tekst)}</span>')


def _vinkje(ok):
    return {True: "groen", False: "rood", None: "niet gebouwd"}[ok]


# ── lagen ─────────────────────────────────────────────────────────────────────

def _laag(l):
    bewijs = "".join(f'<li class="{"ja" if b["aanwezig"] else "nee"}">'
                     f'{"✓" if b["aanwezig"] else "✗"} <code>{esc(b["pad"])}</code></li>'
                     for b in l["bewijs"]) or "<li class=nee>— nog geen bewijs benoemd</li>"
    tests = "".join(f'<li class="{"ja" if t["aanwezig"] else "nee"}">'
                    f'{"✓" if t["aanwezig"] else "✗"} <code>{esc(t["pad"])}</code></li>'
                    for t in l["tests"])
    uitslag = "".join(f'<li class="{"ja" if u["groen"] else "nee"}">'
                      f'<code>{esc(u["pad"])}</code> — {esc(u["laatste_regel"])}</li>'
                      for u in l["uitslagen"])
    return (f'<details class="kaart"><summary><span class="nr">{l["nr"]}</span>'
            f'<span class="naam">{esc(l["naam"])}</span>'
            f'<span class="wie">{esc(l["repo"])}</span>{_pil(l["lamp"], l["lamp"])}</summary>'
            f'<div class="body"><h4>Bewijs</h4><ul>{bewijs}</ul>'
            + (f'<h4>Tests</h4><ul>{tests}</ul>' if tests else "")
            + (f'<h4>Uitslag</h4><ul>{uitslag}</ul>' if uitslag else "")
            + '</div></details>')


# ── grenzen ───────────────────────────────────────────────────────────────────

CONTROLE_NAAM = {"imports": "geen verboden import",
                 "schrijft_niet": "schrijft nergens",
                 "netwerkvrij": "geen netwerk",
                 "klokvrij": "geen klok, geen locale"}


def _systeem(s):
    pillen = "".join(
        _pil(CONTROLE_NAAM[k], _vinkje(c["ok"]))
        + (f' <span class="citaat">“{esc(c["bewijs"])}”</span>' if c["ok"] is False else "")
        for k, c in s["controles"].items())
    lamp = "niet gebouwd" if not s["gebouwd"] else ("groen" if s["ok"] else "rood")
    return (f'<details class="kaart"><summary><span class="nr">{s["nr"]}</span>'
            f'<span class="naam">{esc(s["naam"])}</span>'
            f'<span class="wie"><code>{esc(s["module"])}.py</code> · {esc(s["repo"])}</span>'
            f'{_pil(lamp, lamp)}</summary><div class="body">'
            f'<dl><dt>leest</dt><dd>{esc(", ".join(s.get("bronnen", [])) or "—")}</dd>'
            f'<dt>permissie</dt><dd>{esc(", ".join(s.get("permissies", [])) or "geen")}</dd>'
            f'<dt>data staat</dt><dd>{esc(s.get("residentie", "—"))}</dd>'
            f'<dt>verlaat tenant</dt><dd>{esc(s.get("verlaat_tenant", "—"))}</dd></dl>'
            f'<p class="pillen">{pillen}</p></div></details>')


# ── tests en ketens ───────────────────────────────────────────────────────────

def _test(t):
    lamp = _vinkje(t["groen"])
    return (f'<tr><td class="wie">{esc(t["repo"])}</td><td><code>{esc(t["bestand"])}</code></td>'
            f'<td>{_pil({"groen": "groen", "rood": "rood"}.get(lamp, "niet gedraaid"), lamp)}</td>'
            f'<td class="mute">{esc(t["laatste_regel"])}</td></tr>')


def _audit(a):
    lamp = {True: "groen", False: "rood", None: "niet gebouwd"}[a["ok"]]
    tekst = {True: "intact", False: "gebroken", None: "niet uitvoerbaar"}[a["ok"]]
    return (f'<tr><td class="wie">{esc(a["repo"])}</td><td>{esc(a["naam"])}</td>'
            f'<td>{_pil(tekst, lamp)}</td>'
            f'<td class="mute">{esc(a["uitvoer"])}</td></tr>')


# ── de pagina ─────────────────────────────────────────────────────────────────

PAGE = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{project} — controlekamer</title>
<style>
  :root {{ --teal:#009b8f; --teal-deep:#007c72; --teal-tint:#e3f4f2; --blue:#255fa9;
          --warn:#b97b17; --warn-tint:#fdf5e3; --danger:#cf3f3a; --good:#1d7d43;
          --paper:#f2f5f7; --card:#fff; --ink:#10131a; --ink-2:#3d4453; --mute:#79808f;
          --faint:#a5abb8; --line:#e3e7ee; --line-soft:#edf0f5; --r:13px;
          --sans:-apple-system,BlinkMacSystemFont,system-ui,"Segoe UI",sans-serif;
          --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.5 var(--sans); }}
  .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 20px 80px; }}
  .eyebrow {{ font: 12px var(--mono); letter-spacing: .08em; text-transform: uppercase;
             color: var(--teal-deep); }}
  h1 {{ font-size: 30px; line-height: 1.2; margin: 6px 0 4px; }}
  .sub-head {{ color: var(--mute); margin-bottom: 22px; max-width: 62ch; }}
  .tally {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }}
  .tally div {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--r);
               padding: 10px 14px; font: 13px var(--mono); }}
  .tally b {{ display: block; font: 700 21px var(--mono); color: var(--ink); }}
  h2 {{ font-size: 15px; margin: 34px 0 4px; font-family: var(--mono); text-transform: uppercase;
       letter-spacing: .07em; color: var(--mute); }}
  .uitleg {{ color: var(--mute); font-size: 13px; margin: 0 0 10px; max-width: 62ch; }}
  .kaart {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--r);
           margin-bottom: 6px; }}
  summary {{ cursor: pointer; padding: 11px 14px; display: flex; gap: 12px; align-items: baseline;
            flex-wrap: wrap; font-size: 14px; list-style: none; }}
  summary::-webkit-details-marker {{ display: none; }}
  .nr {{ font: 700 13px var(--mono); color: var(--faint); min-width: 22px; }}
  .naam {{ flex: 1; min-width: 200px; font-weight: 600; }}
  .wie {{ font: 12px var(--mono); color: var(--mute); }}
  .pil {{ display: inline-block; font: 11px var(--mono); padding: 2px 8px; border-radius: 999px;
         border: 1px solid; white-space: nowrap; }}
  .body {{ padding: 0 14px 12px 48px; font-size: 13px; }}
  .body h4 {{ font: 11px var(--mono); letter-spacing: .07em; text-transform: uppercase;
             color: var(--mute); margin: 10px 0 4px; }}
  .body ul {{ margin: 0; padding-left: 0; list-style: none; }}
  .body li {{ margin: 3px 0; }}
  li.nee {{ color: var(--mute); }}
  code {{ font: 12px var(--mono); background: var(--paper); padding: 1px 5px; border-radius: 4px; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 8px 0; }}
  dt {{ font: 11px var(--mono); color: var(--mute); text-transform: uppercase; letter-spacing: .06em; }}
  dd {{ margin: 0; }}
  .pillen {{ margin: 8px 0 0; line-height: 2; }}
  .citaat {{ color: var(--danger); font-size: 12px; margin-right: 10px; }}
  .mute {{ color: var(--mute); }}
  .scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line);
          border-radius: var(--r); overflow: hidden; font-size: 13px; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }}
  tr:last-child td {{ border-bottom: 0; }}
  .adr {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--r);
         padding: 10px 14px; margin-bottom: 6px; font-size: 14px; }}
  .adr b {{ font: 700 12px var(--mono); color: var(--teal-deep); margin-right: 8px; }}
  .adr p {{ margin: 3px 0 0; color: var(--ink-2); font-size: 13px; }}
  .note {{ color: var(--mute); font-size: 13px; margin-top: 28px; max-width: 62ch; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">AI-laag · {tenant_doel}</div>
  <h1>{project} — controlekamer</h1>
  <p class="sub-head">Welke laag staat, wat elk systeem leest en met welke permissie, waar de
  data staat en wat de tenant verlaat. Alles op deze pagina is gemeten uit bestanden, tests en
  ketens — behalve de beslissingen, die zijn opgeschreven omdat je ze niet uit code kunt aflezen.</p>

  <div class="tally">
    <div><b>{lagen_gebouwd}/{lagen_totaal}</b> lagen gebouwd</div>
    <div><b>{systemen_gebouwd}/{systemen_totaal}</b> systemen gebouwd</div>
    <div><b>{grenzen_rood}</b> grenzen rood</div>
    <div><b>{tests_tally}</b> {tests_label}</div>
    <div><b>{ketens}</b> ketens</div>
    <div><b>{beslissingen}</b> beslissingen</div>
  </div>

  <h2>Lagen</h2>
  <p class="uitleg">Gebouwd = elk benoemd bewijsbestand bestaat. Getest = de test bestaat.
  Groen = hij slaagt nu (alleen met <code>?run=1</code>).</p>
  {lagen}

  <h2>Grenzen per systeem</h2>
  <p class="uitleg">De linkerhelft van elke kaart is de claim uit <code>layers.json</code>.
  De pillen zijn gemeten tegen de code: een verboden import, een schrijfwerkwoord naast een
  netwerk-import. Daarboven, één keer per repo: een Graph-permissie in een Entra-script die
  geen enkel systeem claimt.</p>
  {permissies}
  {systemen}

  <h2>Tests en ketens</h2>
  <p class="uitleg">Elke <code>test_*.py</code> in elke repo, met zijn laatste regel — de suites
  eindigen met één zin die zegt wat ze bewaken. Daaronder de hash-ketens.</p>
  <div class="scroll"><table>{tests}</table></div>
  <div class="scroll" style="margin-top:8px"><table>{audits}</table></div>

  <h2>Beslissingen</h2>
  <p class="uitleg">{adr_uitleg}</p>
  {adrs}

  <p class="note">Gemeten op <b>{gemeten_op}</b> — niet opgeschreven, behalve de beslissingen.
  Repo's: {repos}.{worktree}</p>
</div>
</body>
</html>"""


def _permissies(m):
    """Eén regel boven de kaarten: wat is geclaimd, en wat staat er in code dat niemand claimt."""
    geclaimd = ", ".join(m["permissies_geclaimd"]) or "geen"
    if not m["vreemde_permissies"]:
        return (f'<p class="pillen">{_pil("alleen geclaimde permissies in code", "groen")} '
                f'<span class="mute">geclaimd: {esc(geclaimd)}</span></p>')
    return "".join(
        f'<p class="pillen">{_pil("permissie die niemand claimt", "rood")} '
        f'<span class="citaat">“{esc(v["permissie"])} in {esc(v["bestand"])}”</span>'
        f'<span class="mute">· {esc(v["repo"])}</span></p>' for v in m["vreemde_permissies"])


def html(m):
    sam = m["samenvatting"]
    ketens = {True: "intact", False: "GEBROKEN", None: "geen"}[sam["ketens_intact"]]
    gedraaid = any(t["groen"] is not None for t in m["tests"])
    tests_tally = f'{sam["tests_groen"]}/{sam["tests_totaal"]}' if gedraaid else sam["tests_totaal"]
    tests_label = "tests groen" if gedraaid else "tests (niet gedraaid — ?run=1)"
    adrs = m["beslissingen"]
    if adrs["aanwezig"]:
        adr_uitleg = f'Uit <code>{esc(adrs["pad"])}</code>.'
        adr_html = "".join(
            f'<div class="adr"><b>{esc(a["nr"])}</b>{esc(a["titel"])}'
            f'<p>{esc(a["eerste_regel"].replace("`", "").replace("*", ""))}</p></div>'
            for a in adrs["lijst"]) \
            or '<div class="adr">' + _pil("nog geen ADR", "rood") + "</div>"
    else:
        adr_uitleg = "Het beslissingenbestand ontbreekt."
        adr_html = '<div class="adr">' + _pil("ARCHITECTURE.md ontbreekt", "rood") + \
                   f' <span class="mute">{esc(adrs["pad"])}</span></div>'
    return PAGE.format(
        project=esc(m["project"]), tenant_doel=esc(m["tenant_doel"]),
        lagen="\n  ".join(_laag(l) for l in m["lagen"]),
        systemen="\n  ".join(_systeem(s) for s in m["systemen"]),
        permissies=_permissies(m),
        tests="".join(_test(t) for t in m["tests"]) or "<tr><td>geen tests gevonden</td></tr>",
        audits="".join(_audit(a) for a in m["audits"]) or "<tr><td>geen ketens benoemd</td></tr>",
        adr_uitleg=adr_uitleg, adrs=adr_html, ketens=ketens,
        tests_tally=tests_tally, tests_label=tests_label, gemeten_op=esc(m["gemeten_op"]),
        worktree=(" <b>Let op:</b> " + esc(", ".join(m["overrides"])) +
                  " is een overschreven pad (worktree), niet de hoofdrepo.") if m["overrides"] else "",
        repos=esc(", ".join(f"{k} → {v}" for k, v in m["repos"].items())),
        **{k: sam[k] for k in ("lagen_gebouwd", "lagen_totaal", "systemen_gebouwd",
                                "systemen_totaal", "grenzen_rood", "beslissingen")})


RUNS_PAGE = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Runs — controlekamer</title>
<style>
  :root {{ --teal:#009b8f; --danger:#cf3f3a; --good:#1d7d43; --mute:#6b7280;
          --lijn:#e5e7eb; --grond:#fbfbfa; }}
  body {{ font:15px/1.5 -apple-system,system-ui,sans-serif; background:var(--grond);
         color:#111; margin:0; padding:2rem; max-width:60rem; }}
  a {{ color:var(--teal); }}
  .kaart {{ border:1px solid var(--lijn); border-left:4px solid var(--mute);
           border-radius:6px; background:#fff; padding:.6rem .9rem; margin:.5rem 0; }}
  .kaart.rood {{ border-left-color:var(--danger); }}
  .kaart.groen {{ border-left-color:var(--good); }}
  .kaart.grijs {{ border-left-color:var(--mute); }}
  summary {{ cursor:pointer; }}
  .meta, .mute {{ color:var(--mute); font-size:.88em; }}
  ul.rood {{ color:var(--danger); margin:.4rem 0 0 1rem; padding:0; }}
</style>
</head>
<body>
<p class=meta><a href="/">← controlekamer</a> · <a href="/flow">stroom</a></p>
{inhoud}
</body>
</html>
"""


def runs_html(rijen):
    """Eén regel per agentrun: wat hij deed, en waarom hij rood is."""
    kop = ("<h1>Runs</h1><p class=meta>Wat elke agentrun deed — "
           "gemeten aan zijn transcript, niet aan zijn exitgetal.</p>")
    if not rijen:
        return RUNS_PAGE.format(inhoud=kop + "<p>Geen runs in Vibe Kanban.</p>")
    blokken = []
    for r in rijen:
        lamp = "rood" if r["rood"] else ("grijs" if r["beurten"] is None else "groen")
        tools = ", ".join(f"{esc(k)} {v}" for k, v in sorted(r["tools"].items())) or "—"
        duur = f"{r['duur_s'] / 60:.1f} min" if r.get("duur_s") else "—"
        redenen = "".join(f"<li>{esc(x)}</li>" for x in r["rood"])
        blokken.append(
            f"<details class='kaart {lamp}'><summary>"
            f"<b>{esc(r['workspace'])}</b> · {esc(r['status'] or '—')} "
            f"exit {r['exit_code']} · "
            f"{r['beurten'] if r['beurten'] is not None else '?'} beurten · "
            f"{len(r['geschreven'])} bestanden</summary>"
            f"<p class=meta>tak {esc(r['branch'] or '—')} · "
            f"gestart {esc(r['gestart'] or '—')} · {duur}</p>"
            f"<p>tools: {tools}</p>"
            f"<p>geschreven: {esc(', '.join(r['geschreven'])) or 'niets'}</p>"
            f"<p>poort: {esc(str(r['cleanup'])) if r['cleanup'] else 'niet gedraaid'}</p>"
            + (f"<ul class=rood>{redenen}</ul>" if redenen else "")
            + "</details>")
    return RUNS_PAGE.format(inhoud=kop + "".join(blokken))


# ── de stroom: het canvas (React Flow, gebouwd in web/dist) ──────────────────
# `npm run build` in web/ levert dist/; die staat in git, zodat deze server geen
# Node nodig heeft. Alles wat het canvas toont komt uit /flow.json en /events.

DIST = pathlib.Path(__file__).resolve().parent / "web" / "dist"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".map": "application/json"}


def _dist_bestand(pad):
    """Het bestand onder web/dist voor een /flow[/...]-pad, of None. Nooit erbuiten."""
    rel = pad[len("/flow"):].lstrip("/") or "index.html"
    doel = (DIST / rel).resolve()
    if DIST.resolve() not in doel.parents or not doel.is_file():
        return None
    return doel


def stroom_html(inline=None):
    """index.html met JS en CSS erin gebakken; met `inline` ook alle niveaus (voor --export)."""
    html_ = (DIST / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'<script type="module"[^>]*src="([^"]+)"[^>]*></script>', html_):
        src = (DIST / m.group(1).replace("/flow/", "", 1)).read_text(encoding="utf-8")
        html_ = html_.replace(m.group(0), "<script type=\"module\">" + src + "</script>")
    for m in re.finditer(r'<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', html_):
        css = (DIST / m.group(1).replace("/flow/", "", 1)).read_text(encoding="utf-8")
        html_ = html_.replace(m.group(0), "<style>" + css + "</style>")
    if inline is not None:
        html_ = html_.replace("<head>", "<head><script>window.STROOM=" +
                              json.dumps(inline, ensure_ascii=False) + "</script>", 1)
    return html_


def export(manifest_pad, map_, run_tests=False):
    """Twee losse HTML-bestanden die zonder server werken — om te delen."""
    m = meet.laad(manifest_pad)
    map_ = pathlib.Path(map_).expanduser()
    map_.mkdir(parents=True, exist_ok=True)
    naam = m.get("project", "project").lower()
    kamer = map_ / f"{naam}-controlekamer.html"
    kamer.write_text(html(meet.meet(m, run_tests)), encoding="utf-8")
    alle = {"": flow.stroom(m)}
    for sys_ in m.get("systemen", []):
        alle[sys_["module"]] = flow.stroom(m, sys_["module"])
    stroom = map_ / f"{naam}-stroom.html"
    stroom.write_text(stroom_html(alle), encoding="utf-8")
    return [kamer, stroom]


# ── server ────────────────────────────────────────────────────────────────────

def check(m):
    """De poort voor een werkbank: alleen de overschreven repo's tellen, exit 1 bij rood.

    Zonder --repo telt alles — maar dan blokkeert test_entra (heeft az nodig) elke
    merge, en dat is niet wat een werkbank-poort moet doen. De poort gaat over het
    werk in die worktree, niet over de hele wereld.
    """
    scope = set(m["overrides"]) or set(m["repos"])
    rood = []
    for s_ in m["systemen"]:
        if s_["repo"] in scope and not s_["ok"]:
            rood.append(f"grens rood: {s_['naam']} — " + "; ".join(
                f"{k}: {c['bewijs']}" for k, c in s_["controles"].items() if c["ok"] is False))
    for v in m["vreemde_permissies"]:
        if v["repo"] in scope:
            rood.append(f"permissie die niemand claimt: {v['permissie']} in {v['bestand']}")
    for t in m["tests"]:
        if t["repo"] in scope and t["groen"] is False:
            rood.append(f"test rood: {t['bestand']} — {t['laatste_regel']}")
    groen = sum(1 for t in m["tests"] if t["repo"] in scope and t["groen"])
    print(f"gemeten {m['gemeten_op']} · repo's {', '.join(sorted(scope))} · {groen} tests groen")
    for r in rood:
        print("✗", r)
    if not rood:
        print("✓ niets rood in", ", ".join(sorted(scope)))
    return 0 if not rood else 1


def xy(m):
    """Eén regel voor xyOps: data voor buckets en workflows, een tabel voor het jobrapport.

    Exit 1 alleen op een rode grens of een gebroken keten — dat is 'stop'. Rode
    tests zijn een waarschuwing: test_entra is rood zolang az niet ingelogd is en
    dat mag geen alarm om het kwartier worden.
    """
    sam = m["samenvatting"]
    rows = [[str(l["nr"]), l["naam"], l["lamp"]] for l in m["lagen"]]
    rows += [[str(s_["nr"]), s_["naam"],
              "niet gebouwd" if not s_["gebouwd"] else ("groen" if s_["ok"] else "rood")]
             for s_ in m["systemen"]]
    rood = [f"{s_['naam']}: " + "; ".join(f"{k} — {c['bewijs']}" for k, c in s_["controles"].items()
                                          if c["ok"] is False) for s_ in m["systemen"] if not s_["ok"]]
    rood += [f"permissie die niemand claimt: {v['permissie']} in {v['bestand']}"
             for v in m["vreemde_permissies"]]
    rood += [f"keten gebroken: {a['naam']} — {a['uitvoer']}" for a in m["audits"] if a["ok"] is False]
    waarschuwing = [f"test rood: {t['bestand']} — {t['laatste_regel'][:120]}"
                    for t in m["tests"] if t["groen"] is False]
    waarschuwing += [f"sonde niet uitvoerbaar: {a['naam']} — {a['uitvoer']}"
                     for a in m["audits"] if a["ok"] is None]
    uit = {
        "xy": True,
        "data": {**{k: (int(v) if isinstance(v, bool) else v) for k, v in sam.items()
                    if v is not None}, "gemeten_op": m["gemeten_op"], "project": m["project"]},
        "table": {"title": "Lagen en systemen", "cols": ["#", "naam", "lamp"], "rows": rows,
                  "caption": f"gemeten {m['gemeten_op']}"},
        "markdown": "\n".join(["### Rood"] + [f"- {r}" for r in rood] if rood else ["Niets rood."])
                    + ("\n\n### Waarschuwingen\n" + "\n".join(f"- {w}" for w in waarschuwing)
                       if waarschuwing else ""),
    }
    if waarschuwing:
        uit["warning"] = f"{len(waarschuwing)} waarschuwing(en)"
    live.noteer("meting", f"gemeten {m['gemeten_op']}: {sam['grenzen_rood']} grenzen rood, "
                f"{sam['tests_rood']} tests rood", ok=not rood)
    return uit, (1 if rood else 0)


def systeem_xy(m, module):
    """Eén systeem gemeten, als één xyOps-jobregel.

    Dit is wat een knoop op het xyOps-canvas is: geen plaatje van een systeem maar
    de meting ervan, die draait, kleurt en een rapport achterlaat. Rood = deze
    module heeft een grens overschreden of zijn eigen test faalt; dat is iets
    anders dan `--xy`, waar een rode test infrastructuur kan zijn (az niet ingelogd).
    """
    s_ = next((x for x in m.get("systemen", []) if x["module"] == module), None)
    if s_ is None:
        return {"xy": True, "warning": f"onbekend systeem: {module}"}, 0

    g = meet.grens_status(s_, m["repos"])
    repo = m["repos"][s_["repo"]]
    test = f"test_{module}.py"
    if (repo / test).exists():
        groen, staart = meet._test_draait(repo, test)
    else:
        groen, staart = None, "geen test"

    rows = [[meet_naam, {True: "groen", False: "ROOD", None: "n.v.t."}[c["ok"]], c["bewijs"] or ""]
            for meet_naam, c in g["controles"].items()]
    rows.append(["test", {True: "groen", False: "ROOD", None: "geen"}[groen], staart[:120]])

    rood = [f"{k} — {c['bewijs']}" for k, c in g["controles"].items() if c["ok"] is False]
    if groen is False:
        rood.append(f"test rood — {staart[:150]}")

    uit = {
        "xy": True,
        "data": {"systeem": s_["nr"], "module": module, "naam": s_["naam"],
                 "gebouwd": int(g["gebouwd"]), "grens_ok": int(g["ok"]),
                 "test_groen": None if groen is None else int(groen),
                 "permissies": ", ".join(s_.get("permissies", [])) or "geen",
                 "verlaat_tenant": s_.get("verlaat_tenant", "")},
        "table": {"title": f"Systeem {s_['nr']} · {s_['naam']}",
                  "cols": ["controle", "uitslag", "bewijs"], "rows": rows,
                  "caption": f"{module}.py · leest: " + (", ".join(s_.get("bronnen", [])) or "—")},
        "markdown": ("### Rood\n" + "\n".join(f"- {r}" for r in rood)) if rood
                    else f"Niets rood in `{module}.py`.",
    }
    if not g["gebouwd"]:
        uit["warning"] = "nog niet gebouwd"
    return uit, (1 if rood else 0)


def bewaking_xy(m):
    """De omgevingsgrenzen als één xyOps-knoop: loopback, funnel, sleutels, poort."""
    b = bewaking.meet_bewaking(m)
    rows = [[naam, {True: "groen", False: "ROOD", None: "onbekend"}[c["ok"]], c["bewijs"] or ""]
            for naam, c in b["controles"].items()]
    rood = [f"{naam} — {c['bewijs']}" for naam, c in b["controles"].items() if c["ok"] is False]
    grijs = [f"{naam} — {c['bewijs']}" for naam, c in b["controles"].items() if c["ok"] is None]
    uit = {
        "xy": True,
        "data": {"bewaking_ok": int(b["ok"]),
                 "rood": len(rood), "onbekend": len(grijs)},
        "table": {"title": "Bewaking · omgevingsgrenzen",
                  "cols": ["controle", "uitslag", "bewijs"], "rows": rows,
                  "caption": "gemeten op deze machine, niet beloofd"},
        "markdown": ("### Rood\n" + "\n".join(f"- {r}" for r in rood)) if rood
                    else "Alle grenzen staan.",
    }
    if grijs:
        uit["warning"] = f"{len(grijs)} controle(s) niet uitvoerbaar"
    return uit, (1 if rood else 0)


def _overrides(args):
    uit = {}
    for i, a in enumerate(args):
        if a == "--repo":
            naam, _, pad = args[i + 1].partition("=")
            uit[naam] = pad
    return uit


def serve(manifest_pad, port=PORT, overrides=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            run = parse_qs(u.query).get("run", ["0"])[0] == "1"
            if u.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for e in live.events(manifest_pad, overrides):
                        self.wfile.write(f"data: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if u.path == "/flow" or u.path.startswith("/flow/"):
                bestand = _dist_bestand(u.path)
                if bestand is None:
                    self.send_error(404)
                    return
                body, ctype = bestand.read_bytes(), MIME.get(bestand.suffix, "application/octet-stream")
            elif u.path == "/flow.json":
                module = parse_qs(u.query).get("module", [None])[0]
                body = json.dumps(flow.stroom(meet.laad(manifest_pad, overrides), module, run),
                                  ensure_ascii=False).encode()
                ctype = "application/json"
            elif u.path == "/runs":
                body = runs_html(waarneming.runs(meet.laad(manifest_pad, overrides))).encode()
                ctype = "text/html; charset=utf-8"
            elif u.path in ("/", "/meet.json"):
                m = meet.meet(meet.laad(manifest_pad, overrides), run_tests=run)
                body = (json.dumps(m, ensure_ascii=False, indent=2) if u.path == "/meet.json"
                        else html(m)).encode()
                ctype = "application/json" if u.path == "/meet.json" else "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            print(f"  {fmt % args}", file=sys.stderr)

    print(f"controlekamer · {manifest_pad} · http://127.0.0.1:{port}  (?run=1 draait de tests)",
          file=sys.stderr)
    # Loopback, altijd. `?run=1` draait testbestanden en /events leest een
    # klant-repo: dat hoort niet op elk wifi-netwerk waar deze Mac op zit.
    # Van buiten = tailnet, via `tailscale serve` (nooit funnel).
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    manifest, ov = args[0], _overrides(args)
    if "--export" in args:
        for pad in export(manifest, args[args.index("--export") + 1], "--run" in args):
            print(pad)
    elif "--serve" in args:
        port = int(args[args.index("--port") + 1]) if "--port" in args else PORT
        serve(manifest, port=port, overrides=ov)
    elif "--check" in args:
        sys.exit(check(meet.meet(meet.laad(manifest, ov), run_tests="--run" in args)))
    elif "--bewaking" in args:
        uit, code = bewaking_xy(meet.laad(manifest, ov))
        print(json.dumps(uit, ensure_ascii=False))
        sys.exit(code)
    elif "--systeem" in args:
        uit, code = systeem_xy(meet.laad(manifest, ov), args[args.index("--systeem") + 1])
        print(json.dumps(uit, ensure_ascii=False))
        sys.exit(code)
    elif "--xy" in args:
        uit, code = xy(meet.meet(meet.laad(manifest, ov), run_tests="--run" in args))
        print(json.dumps(uit, ensure_ascii=False))
        sys.exit(code)
    elif "--runs" in args:
        print(runs_html(waarneming.runs(meet.laad(manifest, ov))))
    elif "--tally" in args:
        naam = args[args.index("--tally") + 1]
        v = meet.meet(meet.laad(manifest, ov), run_tests="--run" in args)["samenvatting"][naam]
        print("" if v is None else int(v))
    else:
        print(html(meet.meet(meet.laad(manifest, ov), run_tests="--run" in args)))
