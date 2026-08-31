"""Wat een agentrun werkelijk deed — gemeten aan zijn transcript, niet aan zijn exitgetal.

Een exit 1 zegt dat het misging, niet waar. Het transcript van de mislukte run van
systeem 5 telt 29 beurten, 8x Read, 7x Bash en **1x Write**: één bestand geschreven,
toen dood. Dat getal lag er al sinds 28 aug; er was geen weergave voor.

Meet, bewaart niets. Elke weergave is een verse meting.

    python3.12 waarneming.py ~/durabo-platform/layers.json
"""

import json
import re
import sqlite3
import subprocess
from pathlib import Path

PROJECTS = Path.home() / ".claude/projects"
SCHRIJFTOOLS = ("Write", "Edit", "NotebookEdit")
TESTNAAM = re.compile(r"^def (test_\w+)", re.M)


def transcriptmap(worktree, projects=PROJECTS):
    """Claude Code codeert het werkpad als mapnaam: elke / en elke . wordt een -.

    Het pad wordt resolved zodat /var-symlinks (macOS: /var → /private/var) matchen
    hoe Claude Code de transcriptdirectory noemt.
    """
    return projects / re.sub(r"[/.]", "-", str(Path(worktree).resolve()))


def leest_transcript(pad):
    """Beurten, tools, geschreven bestanden en duur uit één JSONL-transcript.

    Een kapotte regel wordt overgeslagen — een half weggeschreven laatste regel mag
    de meting van de rest niet kosten.
    """
    beurten, tools, geschreven, tijden = 0, {}, [], []
    with Path(pad).open(encoding="utf-8") as f:
        for regel in f:
            try:
                d = json.loads(regel)
            except ValueError:
                continue
            if d.get("timestamp"):
                tijden.append(d["timestamp"])
            if d.get("type") != "assistant":
                continue
            beurten += 1
            inhoud = (d.get("message") or {}).get("content")
            for blok in inhoud if isinstance(inhoud, list) else []:
                if not isinstance(blok, dict) or blok.get("type") != "tool_use":
                    continue
                naam = blok.get("name", "?")
                tools[naam] = tools.get(naam, 0) + 1
                pad_ = (blok.get("input") or {}).get("file_path")
                if naam in SCHRIJFTOOLS and pad_ and pad_ not in geschreven:
                    geschreven.append(pad_)
    return {"beurten": beurten, "tools": tools, "geschreven": geschreven,
            "duur_s": _duur(tijden), "tijden": tijden}


def _duur(tijden):
    """Seconden tussen eerste en laatste tijdstempel; None als er niets te meten valt."""
    from datetime import datetime
    if len(tijden) < 2:
        return None
    stempels = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in tijden)
    return (stempels[-1] - stempels[0]).total_seconds()


def _aggregeer_sessies(paden):
    """Aggregeer alle transcripts in een worktree: sum beurten, merge tools, union geschreven.

    Berekent duur_s over ALLE sessions (eerste tot laatste timestamp across all files).
    """
    if not paden:
        return {"beurten": None, "tools": {}, "geschreven": [], "duur_s": None}

    beurten_totaal = 0
    tools_totaal = {}
    geschreven_totaal = []
    alle_tijden = []

    for pad in paden:
        t = leest_transcript(pad)
        beurten_totaal += t["beurten"]
        for tool, count in t["tools"].items():
            tools_totaal[tool] = tools_totaal.get(tool, 0) + count
        for bestand in t["geschreven"]:
            if bestand not in geschreven_totaal:
                geschreven_totaal.append(bestand)
        alle_tijden.extend(t["tijden"])

    duur = _duur(alle_tijden)
    return {"beurten": beurten_totaal, "tools": tools_totaal, "geschreven": geschreven_totaal,
            "duur_s": duur}


def _testnamen(tekst):
    return set(TESTNAAM.findall(tekst))


ONLEESBAAR = object()   # git kon niets zeggen — dat is grijs, niet "staat er niet"


def _git(repo, *args):
    """git in deze repo, of None als git zelf niet kon draaien."""
    try:
        return subprocess.run(("git",) + args, cwd=repo, capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _refleesbaar(repo, ref):
    """True als de ref bestaat, False als hij ontbreekt, None als git niet kon draaien."""
    r = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return None if r is None else r.returncode == 0


def _lees(repo, ref, bestand):
    """De inhoud van een bestand op een ref.

    None = het bestand staat daar niet. ONLEESBAAR = git kon het niet zeggen
    (ontbrekende ref, ondiepe kloon, geen git). Die twee mogen nooit samenvallen:
    het eerste is een bevinding, het tweede is grijs.
    """
    r = _git(repo, "show", f"{ref}:{bestand}")
    if r is None:
        return ONLEESBAAR
    if r.returncode == 0:
        return r.stdout
    return None if _refleesbaar(repo, ref) is True else ONLEESBAAR


def _gewijzigd(repo, bereik):
    """Padnamen die dit diff-bereik raakt; None als git dat niet kan zeggen.

    Renames worden niet gedetecteerd: een hernoemd testbestand telt liever één keer
    te veel als verdwenen dan één keer te weinig.
    """
    r = _git(repo, "diff", "--name-only", "-z", "--no-renames", bereik)
    if r is None or r.returncode != 0:
        return None
    return [p for p in r.stdout.split("\0") if p]


def _verdwenen_tests(repo, tak):
    """Elke test die op main staat en op de tak weg is; None als er niet te kijken viel.

    Vergelijkt takken, geen worktrees: vijf van de zes VK-worktrees op deze machine
    bestaan niet meer, de takken wel — en een regel die zwijgt omdat de map weg is,
    maakt een run groen zonder gekeken te hebben.

    Kijkt naar élk testbestand dat tussen main en de tak verschilt, niet alleen naar
    wat de agent schreef: systeem 5, 6 en 7 schreven prijs.py, betaalrun_fixtures.py
    en royalty.py en géén test_*.py, en lieten ondertussen elk één test vallen.
    Een bestand dat op beide refs identiek is kan per definitie geen test missen.
    """
    verschil = _gewijzigd(repo, f"main..{tak}")
    if verschil is None:
        return None
    weg = []
    for bestand in verschil:
        if not (Path(bestand).name.startswith("test_") and bestand.endswith(".py")):
            continue
        op_main = _lees(repo, "main", bestand)
        if op_main is ONLEESBAAR:
            return None
        if op_main is None:
            continue                          # nieuw op de tak: niets te verliezen
        op_tak = _lees(repo, tak, bestand)
        if op_tak is ONLEESBAAR:
            return None
        if op_tak is None:
            # Het hele bestand ontbreekt op de tak. Dat is één bevinding, geen dertig
            # regels: meestal is de tak ouder dan het bestand. Wél zichtbaar, want een
            # tak die zo gemerged wordt neemt die tests mee het graf in.
            weg.append(f"testbestand staat niet op de tak: {bestand} "
                       f"({len(_testnamen(op_main))} tests op main)")
            continue
        for t in sorted(_testnamen(op_main) - _testnamen(op_tak)):
            weg.append(f"test verdwenen t.o.v. main: {t} in {bestand}")
    return weg


def _hoofdrepo(run, repos):
    """De hoofdrepo bij deze run, gekoppeld op pad.

    Op naam koppelen gaat stuk: Vibe Kanban noemt de repo `stride-durabo`, layers.json
    noemt hem `systemen`. Dan vindt `repos.get(...)` niets en zwijgt regel 3 voorgoed —
    groen omdat er niet gekeken is.
    """
    if not run.get("repo_pad"):
        return None
    p = Path(run["repo_pad"]).expanduser().resolve()
    for pad in repos.values():
        q = Path(pad).expanduser()
        if q.resolve() == p:
            return q
    return None


def _waarom(hoofd, tak, anders):
    """Waarom een git-regel niet kon draaien — kort genoeg voor de kaart."""
    if hoofd is None:
        return "geen repo gekoppeld aan deze run"
    if not tak:
        return "de run heeft geen tak"
    if _refleesbaar(hoofd, tak) is False:
        return f"tak {tak} bestaat niet meer"
    return anders


def oordeel(run, repos):
    """(rood, gemeten) — wat er mis is, en welke regels werkelijk gedraaid hebben.

    Groen is verdiend: leeg `rood` én alle drie de regels gemeten. Een regel die niet
    kon draaien staat in `gemeten` met de reden in plaats van True; dat is grijs.
    Een meting die stilvalt mag nooit als groen eindigen.
    """
    rood, gemeten = [], {}
    hoofd = _hoofdrepo(run, repos)
    tak = run.get("branch")

    # regel 1 — heeft deze run iets opgeleverd? De diff van de tak is de grond, niet
    # het aantal Writes: een agent die met `cat > bestand <<EOF` schrijft laat geen
    # Write in zijn transcript achter, maar wel een diff.
    # ponytail: een tak zonder eigen commits en een tak die al in main zit zien er
    # in `main...tak` hetzelfde uit; hier heeft geen enkele VK-tak eigen commits.
    opgeleverd = _gewijzigd(hoofd, f"main...{tak}") if hoofd and tak else None
    if opgeleverd is None:
        gemeten["schreef"] = _waarom(hoofd, tak, "de tak is niet met main te vergelijken")
    else:
        gemeten["schreef"] = True
        if not opgeleverd:
            rood.append("geen enkel bestand geschreven — de agent heeft niets opgeleverd")

    # regel 2 — de poort: nooit gedraaid is rood, gedraaid en afgekeurd óók.
    if run["status"] is None:
        gemeten["poort"] = "geen codingagent-regel in Vibe Kanban"
    elif run["status"] == "running":
        gemeten["poort"] = "de run draait nog"
    else:
        gemeten["poort"] = True
        if run["cleanup"] is None:
            rood.append("de poort heeft nooit gedraaid — er is niets gecontroleerd")
        else:
            p_status, p_exit = run["cleanup"]
            if p_exit not in (0, None):
                rood.append(f"de poort draaide en keurde af — exit {p_exit}")
            elif p_status != "completed":
                rood.append(f"de poort is niet afgerond — status {p_status}")

    # regel 3 — testregressie
    verdwenen = _verdwenen_tests(hoofd, tak) if hoofd and tak else None
    if verdwenen is None:
        gemeten["testregressie"] = _waarom(hoofd, tak, "git kon main en de tak niet lezen")
    else:
        gemeten["testregressie"] = True
        rood += verdwenen
    return rood, gemeten


VK_DB = Path.home() / "Library/Application Support/ai.bloop.vibe-kanban/db.v2.sqlite"

VRAAG = """
select w.name, w.branch, w.container_ref, r.name repo, r.path repo_pad, s.agent_working_dir,
       p.run_reason, p.status, p.exit_code, p.started_at
from workspaces w
join workspace_repos wr on wr.workspace_id = w.id
join repos r on r.id = wr.repo_id
join sessions s on s.workspace_id = w.id
join execution_processes p on p.session_id = s.id
order by p.started_at
"""


def runs(m, vk_db=VK_DB, projects=PROJECTS):
    """Eén rij per VK-workspace: de agentrun, de poort, en wat het transcript zegt.

    None (niet []) als de Vibe Kanban-database er niet is: geen database betekent
    "niet te meten", en dat is iets anders dan "geen runs".
    """
    if not Path(vk_db).exists():
        return None
    con = sqlite3.connect(f"file:{vk_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rijen = con.execute(VRAAG).fetchall()
    con.close()

    uit = {}
    for r in rijen:
        naam = r["name"] or r["branch"]
        w = uit.setdefault(naam, {
            "workspace": naam, "branch": r["branch"], "repo": r["repo"],
            "repo_pad": r["repo_pad"],
            "worktree": str(Path(r["container_ref"]) / r["agent_working_dir"])
                        if r["container_ref"] and r["agent_working_dir"] else None,
            "status": None, "exit_code": None, "gestart": None, "cleanup": None})
        if r["run_reason"] == "codingagent":
            w.update(status=r["status"], exit_code=r["exit_code"], gestart=r["started_at"])
        elif r["run_reason"] == "cleanupscript":
            w["cleanup"] = (r["status"], r["exit_code"])

    for w in uit.values():
        w.update(transcript=None, beurten=None, tools={}, geschreven=[], duur_s=None, sessies=0)
        if not w["worktree"]:
            continue
        transcript_dir = transcriptmap(Path(w["worktree"]), projects)
        sessies = sorted(transcript_dir.glob("*.jsonl")) if transcript_dir.is_dir() else []
        w["sessies"] = len(sessies)
        if not sessies:
            continue
        # Aggregeer ALLE sessies in het worktree
        w["transcript"] = str(transcript_dir)
        w.update(_aggregeer_sessies(sessies))
    for w in uit.values():
        w["rood"], w["gemeten"] = oordeel(w, m.get("repos", {}))
    return sorted(uit.values(), key=lambda w: w["gestart"] or "")
