"""De controlekamer: één pagina over lagen, grenzen, tests en beslissingen.

Deze pagina rekent niets. Elke lamp, elk vinkje en elk citaat komt uit
`meet.py`; hier wordt alleen HTML van gemaakt. Dat is bewust en `test_controlroom`
houdt het zo — een pagina die zelf meet, liegt op den duur.

    python3.12 controlroom.py <layers.json> --html          # naar stdout
    python3.12 controlroom.py <layers.json> --run --html    # mét tests
    python3.12 controlroom.py <layers.json> --serve         # http://127.0.0.1:7415
    python3.12 controlroom.py <layers.json> --run --export ~/Downloads   # twee losse HTML's
"""

import json
import pathlib
import sys
from html import escape as esc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import flow
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
  Repo's: {repos}.</p>
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
        repos=esc(", ".join(f"{k} → {v}" for k, v in m["repos"].items())),
        **{k: sam[k] for k in ("lagen_gebouwd", "lagen_totaal", "systemen_gebouwd",
                                "systemen_totaal", "grenzen_rood", "beslissingen")})


# ── de stroom: het canvas ─────────────────────────────────────────────────────
# Alle data komt uit /flow.json (flow.py). De JS hier legt alleen neer wat hij
# krijgt: kolom = laag, rij = rij. Klik = code in het paneel; dubbelklik op een
# systeem = naar binnen. Geen bibliotheek, geen sleepbare knopen — posities zijn
# geen waarheid, dus ze worden ook niet bewaard.

FLOW_PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stroom</title>
<style>
  :root { --teal:#009b8f; --teal-deep:#007c72; --teal-tint:#e3f4f2; --blue:#255fa9; --blue-tint:#e9eff8;
          --warn:#b97b17; --warn-tint:#fdf5e3; --good:#1d7d43; --paper:#f2f5f7; --card:#fff;
          --ink:#10131a; --ink-2:#3d4453; --mute:#79808f; --faint:#a5abb8; --line:#e3e7ee;
          --sans:-apple-system,BlinkMacSystemFont,system-ui,"Segoe UI",sans-serif;
          --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; display:grid; grid-template-rows:auto 1fr; grid-template-columns:1fr 440px;
         background:var(--paper); color:var(--ink); font:14px/1.5 var(--sans); overflow:hidden; }
  header { grid-column:1/3; display:flex; gap:14px; align-items:baseline; padding:10px 16px;
           border-bottom:1px solid var(--line); background:var(--card); }
  header .eyebrow { font:12px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--teal-deep); }
  header b { font-size:16px; }
  header a { font:12px var(--mono); color:var(--blue); cursor:pointer; }
  header .hint { margin-left:auto; font:12px var(--mono); color:var(--mute); }
  #zoek { font:12px var(--mono); padding:4px 10px; border:1px solid var(--line); border-radius:999px;
          background:var(--paper); width:300px; margin-left:12px; }
  .knoop.dim { opacity:.15; }
  .knoop text.badge { font:600 10px var(--mono); }
  .knoop text.badge.ja { fill:var(--good); } .knoop text.badge.nee { fill:var(--faint); }
  #canvas { overflow:hidden; cursor:grab; position:relative; }
  #canvas:active { cursor:grabbing; }
  svg { width:100%; height:100%; }
  .knoop rect { fill:var(--card); stroke:var(--line); stroke-width:1; rx:10; }
  .knoop.bron rect { stroke:var(--faint); stroke-dasharray:4 3; }
  .knoop.systeem rect { stroke:var(--teal); stroke-width:1.5; }
  .knoop.systeem.niet rect { stroke:var(--faint); fill:var(--paper); }
  .knoop.uitvoer rect { stroke:var(--good); }
  .knoop.data rect { stroke:var(--warn); fill:var(--warn-tint); }
  .knoop.functie rect { stroke:var(--blue); }
  .knoop.gekozen rect { stroke-width:3; }
  .knoop text { font:600 12px var(--sans); fill:var(--ink); pointer-events:none; }
  .knoop text.doc { font:10px var(--mono); fill:var(--mute); font-weight:400; }
  .knoop text.soort { font:9px var(--mono); fill:var(--faint); letter-spacing:.08em; text-transform:uppercase; }
  .pijl { fill:none; stroke:var(--faint); stroke-width:1.4; marker-end:url(#punt); }
  aside { border-left:1px solid var(--line); background:var(--card); overflow:auto; padding:14px 16px; }
  aside h3 { margin:0 0 2px; font:700 14px var(--mono); }
  aside .meta { font:11px var(--mono); color:var(--mute); margin-bottom:10px; }
  aside pre { margin:0; font:11.5px/1.5 var(--mono); white-space:pre-wrap; word-break:break-word;
              background:var(--paper); padding:12px; border-radius:10px; }
  aside dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; font-size:13px; }
  aside dt { font:11px var(--mono); color:var(--mute); text-transform:uppercase; letter-spacing:.06em; }
  aside dd { margin:0; }
  aside .leeg { color:var(--mute); font-size:13px; }
</style></head>
<body>
<header><span class="eyebrow">Stroom</span><b id="titel"></b><a id="terug" hidden>← overzicht</a>
  <input id="zoek" placeholder="filter: Exact-export, Mail.Read, ontbreekt…" autocomplete="off">
  <span class="hint">klik = code · dubbelklik systeem = naar binnen · sleep = pannen · scroll = zoom</span></header>
<div id="canvas"><svg id="svg"><defs>
  <marker id="punt" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0L10 5L0 10z" fill="#a5abb8"/></marker></defs><g id="wereld"></g></svg></div>
<aside id="paneel"><p class="leeg">Klik op een blok.</p></aside>
<script>
const W=210, H=58, GX=90, GY=16, PAD=30;
const svg=document.getElementById('svg'), wereld=document.getElementById('wereld');
const paneel=document.getElementById('paneel'), titel=document.getElementById('titel'), terug=document.getElementById('terug');
let view={x:0,y:0,k:1}, data=null, gekozen=null;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function pos(n){ return {x:PAD+n.laag*(W+GX), y:PAD+n.rij*(H+GY)}; }
function knip(s,n){ s=String(s??''); return s.length>n? s.slice(0,n-1)+'…': s; }
function teken(){
  const by={}; data.nodes.forEach(n=>by[n.id]=n);
  let h='';
  for(const [a,b] of data.edges){ const A=pos(by[a]),B=pos(by[b]); if(!by[a]||!by[b]) continue;
    // in het overzicht stroomt data van bron (links) naar systeem; binnen een systeem
    // roept links-hoog rechts-laag aan, dus de pijl loopt van aanroeper naar aangeroepene
    const van=A.x<B.x? {x:A.x+W,y:A.y+H/2}:{x:A.x,y:A.y+H/2};
    const naar=A.x<B.x? {x:B.x,y:B.y+H/2}:{x:B.x+W,y:B.y+H/2};
    const dx=(naar.x-van.x)/2;
    h+=`<path class="pijl" d="M${van.x} ${van.y} C${van.x+dx} ${van.y} ${naar.x-dx} ${naar.y} ${naar.x} ${naar.y}"/>`; }
  for(const n of data.nodes){ const p=pos(n);
    const kl=['knoop',n.soort, n.soort==='systeem'&&!n.gebouwd?'niet':'', n.id===gekozen?'gekozen':''].join(' ');
    const badge = n.geraakt===true? `<text x="${W-12}" y="16" text-anchor="end" class="badge ja">✓ test</text>`
                : n.geraakt===false? `<text x="${W-12}" y="16" text-anchor="end" class="badge nee">○ geen test</text>` : '';
    h+=`<g class="${kl}" data-id="${esc(n.id)}" transform="translate(${p.x},${p.y})"><rect width="${W}" height="${H}"/>
      <text x="12" y="16" class="soort">${esc(n.soort)}</text>${badge}
      <text x="12" y="33">${esc(knip(n.naam,30))}</text>
      <text x="12" y="48" class="doc">${esc(knip(n.doc,36))}</text></g>`; }
  wereld.innerHTML=h;
  filter();
  wereld.setAttribute('transform',`translate(${view.x},${view.y}) scale(${view.k})`);
  wereld.querySelectorAll('.knoop').forEach(g=>{
    g.addEventListener('click',e=>{ gekozen=g.dataset.id; toon(by[gekozen]); teken(); });
    g.addEventListener('dblclick',e=>{ const n=by[g.dataset.id]; if(n.soort==='systeem'&&n.gebouwd) laad(n.module); });
  });
}
function tekst(n){ return [n.naam,n.doc,n.soort,n.module,...(n.bronnen||[]),...(n.velden||[]),...(n.uitkomsten||[])].join(' ').toLowerCase(); }
function filter(){
  const q=document.getElementById('zoek').value.trim().toLowerCase();
  const by={}; (data?.nodes||[]).forEach(n=>by[n.id]=n);
  wereld.querySelectorAll('.knoop').forEach(g=>g.classList.toggle('dim', !!q && !tekst(by[g.dataset.id]).includes(q)));
}
document.getElementById('zoek').addEventListener('input', filter);
function toon(n){
  if(n.soort==='systeem'||n.soort==='bron'||n.soort==='uitvoer'){
    paneel.innerHTML=`<h3>${esc(n.naam)}</h3><div class="meta">${esc(n.soort)}</div><dl>
      ${n.doc!==undefined?`<dt>${n.soort==='systeem'?'permissie':'toelichting'}</dt><dd>${esc(n.doc)||'—'}</dd>`:''}
      ${n.residentie?`<dt>data staat</dt><dd>${esc(n.residentie)}</dd>`:''}
      ${n.verlaat_tenant?`<dt>verlaat tenant</dt><dd>${esc(n.verlaat_tenant)}</dd>`:''}
      ${n.bronnen?.length?`<dt>leest</dt><dd>${esc(n.bronnen.join(', '))}</dd>`:''}
      ${n.velden?.length?`<dt>velden (gemeten)</dt><dd>${n.velden.map(v=>`<code>${esc(v)}</code>`).join(' ')}</dd>`:''}
      ${n.uitkomsten?.length?`<dt>meldt</dt><dd>${n.uitkomsten.map(v=>`<code>${esc(v)}</code>`).join(' ')}</dd>`:''}
      ${n.module?`<dt>module</dt><dd><code>${esc(n.module)}.py</code> ${n.gebouwd?'— dubbelklik om naar binnen te gaan':'— nog niet gebouwd'}</dd>`:''}</dl>`;
    return; }
  const dek = n.geraakt===true?' · door de test geraakt': n.geraakt===false?' · door geen test geraakt':'';
  paneel.innerHTML=`<h3>${esc(n.naam)}</h3><div class="meta">${esc(n.soort)} · regel ${n.regels[0]}–${n.regels[1]}${dek}</div><pre>${esc(n.code)}</pre>`;
}
const INLINE = window.STROOM || null;   // gezet door --export; anders live van de server
async function laad(module){
  if(INLINE){ data=INLINE[module||'']; }
  else { const run=new URLSearchParams(location.search).get('run')==='1';
    const r=await fetch('/flow.json?'+(module?'module='+encodeURIComponent(module)+'&':'')+(run?'run=1':'')); data=await r.json(); }
  gekozen=null; view={x:0,y:0,k:1};
  titel.textContent=data.titel+(data.fout?' — '+data.fout:''); terug.hidden=!module;
  paneel.innerHTML='<p class="leeg">Klik op een blok.</p>'; teken();
}
terug.onclick=()=>laad(null);
let sleep=null;
svg.addEventListener('mousedown',e=>{ sleep={x:e.clientX-view.x,y:e.clientY-view.y}; });
window.addEventListener('mousemove',e=>{ if(!sleep) return; view.x=e.clientX-sleep.x; view.y=e.clientY-sleep.y;
  wereld.setAttribute('transform',`translate(${view.x},${view.y}) scale(${view.k})`); });
window.addEventListener('mouseup',()=>sleep=null);
svg.addEventListener('wheel',e=>{ e.preventDefault(); const k=Math.min(2.5,Math.max(.3,view.k*(e.deltaY<0?1.1:.9)));
  view.x=e.offsetX-(e.offsetX-view.x)*k/view.k; view.y=e.offsetY-(e.offsetY-view.y)*k/view.k; view.k=k;
  wereld.setAttribute('transform',`translate(${view.x},${view.y}) scale(${view.k})`); },{passive:false});
laad(null);
</script></body></html>"""


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
    inline = "<script>window.STROOM=" + json.dumps(alle, ensure_ascii=False) + "</script>\n<script>"
    stroom = map_ / f"{naam}-stroom.html"
    stroom.write_text(FLOW_PAGE.replace("<script>", inline, 1), encoding="utf-8")
    return [kamer, stroom]


# ── server ────────────────────────────────────────────────────────────────────

def serve(manifest_pad, port=PORT):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            run = parse_qs(u.query).get("run", ["0"])[0] == "1"
            if u.path == "/flow":
                body, ctype = FLOW_PAGE.encode(), "text/html; charset=utf-8"
            elif u.path == "/flow.json":
                module = parse_qs(u.query).get("module", [None])[0]
                body = json.dumps(flow.stroom(meet.laad(manifest_pad), module, run),
                                  ensure_ascii=False).encode()
                ctype = "application/json"
            elif u.path in ("/", "/meet.json"):
                m = meet.meet(meet.laad(manifest_pad), run_tests=run)
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
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    manifest = args[0]
    if "--export" in args:
        for pad in export(manifest, args[args.index("--export") + 1], "--run" in args):
            print(pad)
    elif "--serve" in args:
        serve(manifest)
    else:
        print(html(meet.meet(meet.laad(manifest), run_tests="--run" in args)))
