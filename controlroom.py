"""De controlekamer: één pagina over lagen, grenzen, tests en beslissingen.

Deze pagina rekent niets. Elke lamp, elk vinkje en elk citaat komt uit
`meet.py`; hier wordt alleen HTML van gemaakt. Dat is bewust en `test_controlroom`
houdt het zo — een pagina die zelf meet, liegt op den duur.

    python3.12 controlroom.py <layers.json> --html          # naar stdout
    python3.12 controlroom.py <layers.json> --run --html    # mét tests
    python3.12 controlroom.py <layers.json> --serve         # http://127.0.0.1:7415
"""

import json
import sys
from html import escape as esc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import meet

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
                 "schrijft_niet": "schrijft nergens"}


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
    lamp = "groen" if a["ok"] else "rood"
    return (f'<tr><td class="wie">{esc(a["repo"])}</td><td>{esc(a["naam"])}</td>'
            f'<td>{_pil("intact" if a["ok"] else "gebroken", lamp)}</td>'
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

  <p class="note">Gemeten, niet opgeschreven — behalve de beslissingen. Repo's: {repos}.</p>
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
        tests_tally=tests_tally, tests_label=tests_label,
        repos=esc(", ".join(f"{k} → {v}" for k, v in m["repos"].items())),
        **{k: sam[k] for k in ("lagen_gebouwd", "lagen_totaal", "systemen_gebouwd",
                                "systemen_totaal", "grenzen_rood", "beslissingen")})


# ── server ────────────────────────────────────────────────────────────────────

def serve(manifest_pad, port=PORT):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            run = parse_qs(u.query).get("run", ["0"])[0] == "1"
            if u.path not in ("/", "/meet.json"):
                self.send_error(404)
                return
            m = meet.meet(meet.laad(manifest_pad), run_tests=run)
            body = (json.dumps(m, ensure_ascii=False, indent=2) if u.path == "/meet.json"
                    else html(m)).encode()
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/json" if u.path == "/meet.json" else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            print(f"  {fmt % args}", file=sys.stderr)

    print(f"controlekamer · {manifest_pad} · http://127.0.0.1:{port}  (?run=1 draait de tests)",
          file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    manifest = args[0]
    if "--serve" in args:
        serve(manifest)
    else:
        print(html(meet.meet(meet.laad(manifest), run_tests="--run" in args)))
