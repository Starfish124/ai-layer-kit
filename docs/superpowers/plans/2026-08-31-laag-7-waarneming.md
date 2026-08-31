# Laag 7 · Waarneming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elke agentrun in Vibe Kanban wordt naleesbaar — wat hij deed, hoe lang, welke bestanden hij schreef, en of hij door de poort kwam — gemeten aan zijn eigen transcript, niet aan een exitgetal.

**Architecture:** `waarneming.py` in de kit leest VK's `db.v2.sqlite` (alleen-lezen) voor de runs, koppelt elke worktree aan zijn Claude Code-transcript in `~/.claude/projects/`, en telt daaruit beurten, tools en geschreven bestanden. `controlroom.py` toont dat op `/runs`; het meet zelf niets (`test_controlroom.py` bewaakt dat). Geen opslag, geen daemon: elke weergave is een verse meting.

**Tech Stack:** Python 3.12 standaardbibliotheek (`json`, `re`, `sqlite3`, `subprocess`, `pathlib`). Geen dependencies.

## Global Constraints

- **Python 3.12, uitsluitend standaardbibliotheek.** Geen pip-installatie, in geen enkele taak.
- **Nederlands** in docstrings, functienamen, veldnamen en uitvoer — het idioom van `meet.py`, `flow.py`, `bewaking.py`.
- **Tests zijn assert-scripts**, geen pytest: `def test_...()` plus een `if __name__ == "__main__":` die ze aanroept en `alles goed` print. Draaien met `python3.12 test_waarneming.py`. Zo pikt `meet.tests_overal` ze op (die globt `test_*.py` in de repo-root).
- **`controlroom.py` mag niet meten.** `test_controlroom.py` grept dat het bestand geen `subprocess` en geen `ast` bevat. Alle meetlogica hoort in `waarneming.py`.
- **VK's database wordt alleen-lezen geopend**: `sqlite3.connect(f"file:{VK_DB}?mode=ro", uri=True)`. Nooit schrijven.
- **Ontbrekend gereedschap is grijs, nooit groen** — een run zonder transcript is `onbekend`, geen fout.
- **Geen absolute bewijs-paden in `layers.json`** (kliëntdata via pad); paden met `~` schrijven.

## File Structure

| Bestand | Verantwoordelijkheid |
|---|---|
| `~/ai-layer-kit/waarneming.py` (nieuw) | Meet runs: VK-db → worktree → transcript → tellingen → oordeel |
| `~/ai-layer-kit/test_waarneming.py` (nieuw) | Plant elk rood geval en eist rood; één schone run en eist groen |
| `~/ai-layer-kit/controlroom.py` (wijzigen) | `/runs`-pagina + `--runs`-vlag; toont alleen |
| `~/durabo-platform/layers.json` (wijzigen) | `laag 7 · Waarneming` — grens vóór code |

**Interfaces (het contract tussen de taken):**

```python
transcriptmap(worktree: Path, projects: Path = PROJECTS) -> Path
leest_transcript(pad: Path) -> dict   # {"beurten": int, "tools": dict[str,int],
                                      #  "geschreven": list[str], "duur_s": float|None}
runs(m: dict, vk_db: Path = VK_DB, projects: Path = PROJECTS) -> list[dict]
oordeel(run: dict, repos: dict[str, Path]) -> list[str]   # lege lijst = groen
```

Een `run`-dict: `{"workspace", "branch", "repo", "worktree", "status", "exit_code", "gestart", "cleanup", "transcript", "beurten", "tools", "geschreven", "duur_s", "rood"}`.

---

### Task 1: Transcript lezen

**Files:**
- Create: `~/ai-layer-kit/waarneming.py`
- Test: `~/ai-layer-kit/test_waarneming.py`

**Interfaces:**
- Consumes: niets
- Produces: `transcriptmap(worktree, projects=PROJECTS) -> Path`, `leest_transcript(pad) -> dict`

**Achtergrond die de bouwer nodig heeft.** Claude Code bewaart per werkmap een transcriptmap onder `~/.claude/projects/`. De mapnaam is het absolute pad met elke `/` én elke `.` vervangen door `-`. Gemeten voorbeeld: worktree `/private/var/folders/gj/…/T/vibe-kanban-worktrees-0b6d-systeem-5-prijsc/stride-durabo` wordt `-private-var-folders-gj-…-T-vibe-kanban-worktrees-0b6d-systeem-5-prijsc-stride-durabo`, en `/Users/sarveshsingh/.config/deck/grid-stride` wordt `-Users-sarveshsingh--config-deck-grid-stride` (de dubbele `-` komt van de punt in `.config`).

In het JSONL heeft elke regel een `type`. Alleen `assistant` en `user` dragen een `message`-dict; bij `assistant` is `message["content"]` een lijst blokken, en een blok met `"type": "tool_use"` heeft `name` en `input`. `timestamp` is ISO-8601 met `Z`. Schrijvende tools zijn `Write`, `Edit`, `NotebookEdit`; het pad staat in `input["file_path"]`.

- [ ] **Step 1: Schrijf de falende test**

Maak `test_waarneming.py`:

```python
"""Wat een agentrun deed, gemeten aan zijn transcript.

    python3.12 test_waarneming.py
"""

import json
import tempfile
from pathlib import Path

import waarneming

TMP = Path(tempfile.mkdtemp(prefix="ai-layer-kit-waarneming-"))


def _transcript(pad, regels):
    pad.parent.mkdir(parents=True, exist_ok=True)
    with pad.open("w", encoding="utf-8") as f:
        for r in regels:
            f.write(json.dumps(r) + "\n")


def _beurt(ts, blokken):
    return {"type": "assistant", "timestamp": ts, "message": {"content": blokken}}


def _tool(naam, **inp):
    return {"type": "tool_use", "name": naam, "input": inp}


def test_de_mapnaam_vervangt_schuine_streep_en_punt():
    assert waarneming.transcriptmap(Path("/Users/x/.config/deck"), Path("/p")) == \
        Path("/p/-Users-x--config-deck")


def test_het_transcript_telt_beurten_tools_en_geschreven_bestanden():
    pad = TMP / "t1" / "sessie.jsonl"
    _transcript(pad, [
        {"type": "last-prompt", "content": None},
        _beurt("2026-08-28T11:39:44.145Z", [_tool("Read", file_path="a.py")]),
        _beurt("2026-08-28T11:41:00.000Z", [_tool("Write", file_path="prijs.py"),
                                            _tool("Bash", command="ls")]),
        {"type": "user", "timestamp": "2026-08-28T11:41:01.000Z", "message": {"content": "ok"}},
    ])
    t = waarneming.leest_transcript(pad)
    assert t["beurten"] == 2, t
    assert t["tools"] == {"Read": 1, "Write": 1, "Bash": 1}, t
    assert t["geschreven"] == ["prijs.py"], t
    assert 76.0 < t["duur_s"] < 77.0, t


def test_een_kapotte_regel_kost_geen_meting():
    pad = TMP / "t2" / "sessie.jsonl"
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text('{"type":"assistant"\nnog kapotter\n', encoding="utf-8")
    assert waarneming.leest_transcript(pad)["beurten"] == 0


if __name__ == "__main__":
    for naam, fn in sorted(globals().items()):
        if naam.startswith("test_"):
            fn()
    print("alles goed")
```

- [ ] **Step 2: Draai hem en zie hem falen**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `ModuleNotFoundError: No module named 'waarneming'`

- [ ] **Step 3: Schrijf de minimale implementatie**

Maak `waarneming.py`:

```python
"""Wat een agentrun werkelijk deed — gemeten aan zijn transcript, niet aan zijn exitgetal.

Een exit 1 zegt dat het misging, niet waar. Het transcript van de mislukte run van
systeem 5 telt 29 beurten, 8x Read, 7x Bash en **1x Write**: één bestand geschreven,
toen dood. Dat getal lag er al sinds 28 aug; er was geen weergave voor.

Meet, bewaart niets. Elke weergave is een verse meting.

    python3.12 waarneming.py ~/durabo-platform/layers.json
"""

import json
import re
from pathlib import Path

PROJECTS = Path.home() / ".claude/projects"
SCHRIJFTOOLS = ("Write", "Edit", "NotebookEdit")


def transcriptmap(worktree, projects=PROJECTS):
    """Claude Code codeert het werkpad als mapnaam: elke / en elke . wordt een -."""
    return projects / re.sub(r"[/.]", "-", str(worktree))


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
            "duur_s": _duur(tijden)}


def _duur(tijden):
    """Seconden tussen eerste en laatste tijdstempel; None als er niets te meten valt."""
    from datetime import datetime
    if len(tijden) < 2:
        return None
    stempels = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in tijden)
    return (stempels[-1] - stempels[0]).total_seconds()
```

- [ ] **Step 4: Draai de test tot hij slaagt**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `alles goed`

- [ ] **Step 5: Commit**

```bash
cd ~/ai-layer-kit
git add waarneming.py test_waarneming.py
git commit -m "Waarneming: lees een agenttranscript — beurten, tools, geschreven bestanden, duur"
```

---

### Task 2: De runs uit Vibe Kanban

**Files:**
- Modify: `~/ai-layer-kit/waarneming.py`
- Test: `~/ai-layer-kit/test_waarneming.py`

**Interfaces:**
- Consumes: `transcriptmap`, `leest_transcript` uit Task 1
- Produces: `runs(m, vk_db=VK_DB, projects=PROJECTS) -> list[dict]`

**Achtergrond.** VK's database staat in `~/Library/Application Support/ai.bloop.vibe-kanban/db.v2.sqlite`. De vier tabellen die tellen: `workspaces` (`id, name, branch, container_ref, archived, worktree_deleted`), `workspace_repos`, `repos` (`id, name, path`), `sessions` (`id, workspace_id, agent_working_dir`) en `execution_processes` (`session_id, run_reason, status, exit_code, started_at, completed_at`). `run_reason` is `codingagent` voor de agent en `cleanupscript` voor de poort. De worktree is `Path(container_ref) / agent_working_dir` — `agent_working_dir` is relatief (gemeten: `"stride-durabo"`).

`m` is het gemeten manifest van `meet.laad(...)`; alleen `m["repos"]` (naam → `Path`) wordt hier gebruikt.

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `test_waarneming.py`, boven het `__main__`-blok:

```python
import sqlite3

SCHEMA = """
create table repos (id text primary key, name text, path text);
create table workspaces (id text primary key, name text, branch text,
                         container_ref text, archived int, worktree_deleted int);
create table workspace_repos (workspace_id text, repo_id text);
create table sessions (id text primary key, workspace_id text, agent_working_dir text);
create table execution_processes (id text primary key, session_id text, run_reason text,
                                  status text, exit_code int, started_at text);
"""


def _vk_db(pad, container, agent=("completed", 0), cleanup=("completed", 0)):
    con = sqlite3.connect(pad)
    con.executescript(SCHEMA)
    con.execute("insert into repos values ('r1','systemen','/repo')")
    con.execute("insert into workspaces values ('w1','Systeem 5','vk/s5',?,0,0)",
                (str(container),))
    con.execute("insert into workspace_repos values ('w1','r1')")
    con.execute("insert into sessions values ('s1','w1','systemen')")
    con.execute("insert into execution_processes values "
                "('p1','s1','codingagent',?,?,'2026-08-28T11:39:00Z')", agent)
    if cleanup:
        con.execute("insert into execution_processes values "
                    "('p2','s1','cleanupscript',?,?,'2026-08-28T11:50:00Z')", cleanup)
    con.commit()
    con.close()


def test_een_run_koppelt_zijn_worktree_aan_zijn_transcript():
    hier = TMP / "vk1"
    hier.mkdir(parents=True, exist_ok=True)
    container = hier / "worktrees"
    worktree = container / "systemen"
    worktree.mkdir(parents=True)
    projects = hier / "projects"
    _transcript(waarneming.transcriptmap(worktree, projects) / "s.jsonl", [
        _beurt("2026-08-28T11:39:00.000Z", [_tool("Write", file_path="prijs.py")]),
        _beurt("2026-08-28T11:40:00.000Z", [_tool("Bash", command="ls")]),
    ])
    _vk_db(hier / "db.sqlite", container)

    r = waarneming.runs({"repos": {"systemen": Path("/repo")}},
                        vk_db=hier / "db.sqlite", projects=projects)
    assert len(r) == 1, r
    assert r[0]["workspace"] == "Systeem 5"
    assert r[0]["exit_code"] == 0
    assert r[0]["cleanup"] == ("completed", 0)
    assert r[0]["geschreven"] == ["prijs.py"], r[0]
    assert r[0]["beurten"] == 2


def test_zonder_transcript_is_de_run_onbekend_geen_fout():
    hier = TMP / "vk2"
    hier.mkdir(parents=True, exist_ok=True)
    (hier / "worktrees" / "systemen").mkdir(parents=True)
    _vk_db(hier / "db.sqlite", hier / "worktrees")
    r = waarneming.runs({"repos": {"systemen": Path("/repo")}},
                        vk_db=hier / "db.sqlite", projects=hier / "leeg")
    assert r[0]["transcript"] is None, r[0]
    assert r[0]["beurten"] is None, r[0]
```

- [ ] **Step 2: Draai hem en zie hem falen**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `AttributeError: module 'waarneming' has no attribute 'runs'`

- [ ] **Step 3: Schrijf de implementatie**

Voeg toe aan `waarneming.py` (importeer `sqlite3` bovenin):

```python
VK_DB = Path.home() / "Library/Application Support/ai.bloop.vibe-kanban/db.v2.sqlite"

VRAAG = """
select w.name, w.branch, w.container_ref, r.name repo, s.agent_working_dir,
       p.run_reason, p.status, p.exit_code, p.started_at
from workspaces w
join workspace_repos wr on wr.workspace_id = w.id
join repos r on r.id = wr.repo_id
join sessions s on s.workspace_id = w.id
join execution_processes p on p.session_id = s.id
where w.archived = 0 and w.worktree_deleted = 0
order by p.started_at
"""


def runs(m, vk_db=VK_DB, projects=PROJECTS):
    """Eén rij per VK-workspace: de agentrun, de poort, en wat het transcript zegt."""
    if not Path(vk_db).exists():
        return []
    con = sqlite3.connect(f"file:{vk_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rijen = con.execute(VRAAG).fetchall()
    con.close()

    uit = {}
    for r in rijen:
        naam = r["name"] or r["branch"]
        w = uit.setdefault(naam, {
            "workspace": naam, "branch": r["branch"], "repo": r["repo"],
            "worktree": str(Path(r["container_ref"]) / r["agent_working_dir"])
                        if r["container_ref"] else None,
            "status": None, "exit_code": None, "gestart": None, "cleanup": None})
        if r["run_reason"] == "codingagent":
            w.update(status=r["status"], exit_code=r["exit_code"], gestart=r["started_at"])
        elif r["run_reason"] == "cleanupscript":
            w["cleanup"] = (r["status"], r["exit_code"])

    for w in uit.values():
        w.update(transcript=None, beurten=None, tools={}, geschreven=[], duur_s=None)
        if not w["worktree"]:
            continue
        sessies = sorted(transcriptmap(Path(w["worktree"]), projects).glob("*.jsonl")) \
            if transcriptmap(Path(w["worktree"]), projects).is_dir() else []
        if not sessies:
            continue
        # Meerdere sessies in één worktree: de laatste is de run die telt.
        w["transcript"] = str(sessies[-1])
        w.update(leest_transcript(sessies[-1]))
    return sorted(uit.values(), key=lambda w: w["gestart"] or "")
```

- [ ] **Step 4: Draai de test tot hij slaagt**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `alles goed`

- [ ] **Step 5: Draai hem tegen de echte database**

Run: `cd ~/ai-layer-kit && python3.12 -c "
import json, waarneming, meet
m = meet.laad('$HOME/durabo-platform/layers.json')
for r in waarneming.runs(m):
    print(r['workspace'], r['status'], r['exit_code'], 'beurten', r['beurten'],
          'schreef', len(r['geschreven']))"`

Expected: zes runs, waaronder `Systeem 5 — Prijscontrole … failed 1`. Als de lijst leeg is: VK draait met een andere database — controleer `ls -la ~/Library/Application\ Support/ai.bloop.vibe-kanban/`.

- [ ] **Step 6: Commit**

```bash
cd ~/ai-layer-kit
git add waarneming.py test_waarneming.py
git commit -m "Waarneming: runs uit VK's database, gekoppeld aan hun transcript"
```

---

### Task 3: Het oordeel — drie rode regels

**Files:**
- Modify: `~/ai-layer-kit/waarneming.py`
- Test: `~/ai-layer-kit/test_waarneming.py`

**Interfaces:**
- Consumes: `runs()` uit Task 2
- Produces: `oordeel(run, repos) -> list[str]`; `runs()` vult voortaan `run["rood"]`

**Elke regel vangt iets dat echt gebeurd is:**
1. **Nul geschreven bestanden** — systeem 8, poging 1, produceerde geen code.
2. **De poort heeft nooit gedraaid** — `cleanup is None` terwijl de agent klaar is.
3. **Testregressie** — een `def test_` die in `main` staat en in de branch weg is. Dit is het gat waardoor de dragende test uit 5/6/7 verdween.

Regel 3 leest `main` met `git show main:<bestand>` in de hoofdrepo en vergelijkt de testnamen met die in de worktree. Ontbreekt git of de branch, dan is de regel **grijs** (geen oordeel), nooit rood.

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `test_waarneming.py`:

```python
import subprocess


def _git_repo(pad, bestanden):
    pad.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=pad, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=pad, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=pad, check=True)
    for naam, inhoud in bestanden.items():
        (pad / naam).write_text(inhoud, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=pad, check=True)
    subprocess.run(["git", "commit", "-qm", "start"], cwd=pad, check=True)
    return pad


def test_nul_geschreven_bestanden_is_rood():
    run = {"geschreven": [], "cleanup": ("completed", 0), "status": "completed",
           "worktree": None, "repo": "systemen", "transcript": "x"}
    assert any("geen enkel bestand" in r for r in waarneming.oordeel(run, {})), \
        waarneming.oordeel(run, {})


def test_een_poort_die_nooit_draaide_is_rood():
    run = {"geschreven": ["a.py"], "cleanup": None, "status": "completed",
           "worktree": None, "repo": "systemen", "transcript": "x"}
    assert any("poort" in r for r in waarneming.oordeel(run, {})), waarneming.oordeel(run, {})


def test_een_verdwenen_test_is_rood():
    hoofd = _git_repo(TMP / "regressie" / "hoofd", {
        "test_prijs.py": "def test_geen_enkele_waarde_wordt_verzonnen():\n    pass\n"
                         "def test_iets_anders():\n    pass\n"})
    tak = TMP / "regressie" / "tak"
    tak.mkdir(parents=True, exist_ok=True)
    (tak / "test_prijs.py").write_text("def test_iets_anders():\n    pass\n", encoding="utf-8")
    run = {"geschreven": ["test_prijs.py"], "cleanup": ("completed", 0),
           "status": "completed", "worktree": str(tak), "repo": "systemen",
           "transcript": "x"}
    r = waarneming.oordeel(run, {"systemen": hoofd})
    assert any("test_geen_enkele_waarde_wordt_verzonnen" in x for x in r), r


def test_een_schone_run_is_groen():
    hoofd = _git_repo(TMP / "schoon" / "hoofd", {"test_prijs.py": "def test_a():\n    pass\n"})
    tak = TMP / "schoon" / "tak"
    tak.mkdir(parents=True, exist_ok=True)
    (tak / "test_prijs.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    run = {"geschreven": ["test_prijs.py"], "cleanup": ("completed", 0),
           "status": "completed", "worktree": str(tak), "repo": "systemen",
           "transcript": "x"}
    assert waarneming.oordeel(run, {"systemen": hoofd}) == []
```

- [ ] **Step 2: Draai hem en zie hem falen**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `AttributeError: module 'waarneming' has no attribute 'oordeel'`

- [ ] **Step 3: Schrijf de implementatie**

Voeg toe aan `waarneming.py` (importeer `subprocess` bovenin):

```python
TESTNAAM = re.compile(r"^def (test_\w+)", re.M)


def _testnamen(tekst):
    return set(TESTNAAM.findall(tekst))


def _in_main(repo, bestand):
    """De inhoud van een bestand op main, of None als git dat niet kan zeggen."""
    try:
        r = subprocess.run(["git", "show", f"main:{bestand}"], cwd=repo,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def oordeel(run, repos):
    """Wat er mis is met deze run. Lege lijst = groen; onmeetbaar = geen oordeel."""
    rood = []
    if run["transcript"] and not run["geschreven"]:
        rood.append("geen enkel bestand geschreven — de agent heeft niets opgeleverd")
    if run["status"] in ("completed", "failed") and run["cleanup"] is None:
        rood.append("de poort heeft nooit gedraaid — er is niets gecontroleerd")

    hoofd = repos.get(run["repo"])
    tak = Path(run["worktree"]) if run["worktree"] else None
    if hoofd and tak and tak.is_dir():
        for naam in run["geschreven"]:
            if not Path(naam).name.startswith("test_"):
                continue
            was = _in_main(hoofd, Path(naam).name)
            if was is None:
                continue                      # nieuw bestand of geen git: niets te vergelijken
            nu = tak / Path(naam).name
            weg = _testnamen(was) - _testnamen(nu.read_text(encoding="utf-8")
                                               if nu.exists() else "")
            for t in sorted(weg):
                rood.append(f"test verdwenen t.o.v. main: {t} in {Path(naam).name}")
    return rood
```

En in `runs()`, vervang de laatste regel door:

```python
    for w in uit.values():
        w["rood"] = oordeel(w, m.get("repos", {}))
    return sorted(uit.values(), key=lambda w: w["gestart"] or "")
```

- [ ] **Step 4: Draai de test tot hij slaagt**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `alles goed`

- [ ] **Step 5: Commit**

```bash
cd ~/ai-layer-kit
git add waarneming.py test_waarneming.py
git commit -m "Waarneming: drie rode regels — nul writes, poort niet gedraaid, test verdwenen t.o.v. main"
```

---

### Task 4: `/runs` in de controlekamer

**Files:**
- Modify: `~/ai-layer-kit/controlroom.py`
- Test: `~/ai-layer-kit/test_waarneming.py`

**Interfaces:**
- Consumes: `waarneming.runs(m)` uit Task 3
- Produces: `runs_html(rijen) -> str`; CLI-vlag `--runs`; route `/runs`

**Let op de bewaking:** `test_controlroom.py` grept dat `controlroom.py` geen `subprocess` en geen `ast` bevat — de pagina toont, hij meet niet. `import waarneming` is prima; `subprocess` daar aanroepen niet.

Bekijk eerst hoe `flow.py` zijn pagina teruggeeft en hoe `controlroom.py` `/flow` bedient (rond regel 523–552, het CLI-blok, en de HTTP-handler erboven). Volg dat patroon exact: dezelfde CSS-variabelen, dezelfde `<details>`-vorm.

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `test_waarneming.py`:

```python
import controlroom


def test_de_pagina_toont_de_rode_reden_woordelijk():
    rijen = [{"workspace": "Systeem 5", "branch": "vk/s5", "status": "failed",
              "exit_code": 1, "gestart": "2026-08-28T11:39:00Z", "duur_s": 420.0,
              "beurten": 29, "tools": {"Read": 8, "Bash": 7, "Write": 1},
              "geschreven": ["prijs.py"], "cleanup": None, "transcript": "/x/s.jsonl",
              "rood": ["de poort heeft nooit gedraaid — er is niets gecontroleerd"]}]
    h = controlroom.runs_html(rijen)
    assert "Systeem 5" in h
    assert "de poort heeft nooit gedraaid" in h, "de reden moet woordelijk op de pagina staan"
    assert "29" in h and "Write" in h


def test_de_pagina_meet_niet_zelf():
    bron = Path(controlroom.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in bron, "controlroom.py mag niet meten"
```

- [ ] **Step 2: Draai hem en zie hem falen**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `AttributeError: module 'controlroom' has no attribute 'runs_html'`

- [ ] **Step 3: Schrijf de implementatie**

Voeg `import waarneming` toe bij de imports van `controlroom.py`.

**Let op — `PAGE` is niet herbruikbaar.** Die template heeft 21 verplichte placeholders
(`{project}`, `{lagen}`, `{systemen}`, `{tests}`, `{audits}`, `{gemeten_op}`, …) en is de
hoofdpagina. `PAGE.format(titel=…, inhoud=…)` gooit `KeyError`. `/runs` krijgt dus zijn eigen,
kleine template. De accolades in de CSS moeten verdubbeld (`{{`/`}}`), net als in `PAGE`.

Zet naast `PAGE`:

```python
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
```

`esc` bestaat al in `controlroom.py` en wordt overal gebruikt; gebruik hem hier ook —
een branchnaam komt van buiten.

Voeg in het CLI-blok (bij de andere `elif`-takken rond regel 533) toe:

```python
    elif "--runs" in args:
        print(runs_html(waarneming.runs(meet.laad(manifest, ov))))
```

En in `do_GET` (rond regel 471), **na** de `elif u.path == "/flow.json":`-tak en **vóór**
`elif u.path in ("/", "/meet.json"):`, precies dezelfde vorm als de buren:

```python
            elif u.path == "/runs":
                body = runs_html(waarneming.runs(meet.laad(manifest_pad, overrides))).encode()
                ctype = "text/html; charset=utf-8"
```

- [ ] **Step 4: Draai de test tot hij slaagt**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py && python3.12 test_controlroom.py`
Expected: beide `alles goed`

- [ ] **Step 5: Bekijk hem echt**

Run: `cd ~/ai-layer-kit && python3.12 controlroom.py ~/durabo-platform/layers.json --runs > /tmp/runs.html && open /tmp/runs.html`
Expected: zes runs; systeem 5, 6 en 7 rood; systeem 5 toont `Write 1`.

- [ ] **Step 6: Commit**

```bash
cd ~/ai-layer-kit
git add controlroom.py test_waarneming.py
git commit -m "Controlekamer: /runs toont elke agentrun met zijn rode reden woordelijk"
```

---

### Task 5: Laag 7 in `layers.json` + de xyOps-jobknoop

**Files:**
- Modify: `~/durabo-platform/layers.json`
- Test: `~/ai-layer-kit/test_waarneming.py`

**Interfaces:**
- Consumes: alles uit Task 1–4
- Produces: `laag 7` in het manifest; xyOps-event *Controlekamer · runs*

De regel van het huis is grens vóór code — hier andersom, omdat laag 7 de kit zelf meet en niet een systeem van een klant. Daarom komt de laagverklaring in dezelfde commit als de code die hem waarmaakt.

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `test_waarneming.py`:

```python
def test_laag_zeven_staat_in_het_manifest():
    m = json.loads((Path.home() / "durabo-platform/layers.json").read_text(encoding="utf-8"))
    laag = [l for l in m["lagen"] if l["nr"] == 7]
    assert laag, "laag 7 ontbreekt in layers.json"
    assert "waarneming.py" in json.dumps(laag[0]), laag[0]
```

- [ ] **Step 2: Draai hem en zie hem falen**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `AssertionError: laag 7 ontbreekt in layers.json`

- [ ] **Step 3: Voeg de laag toe**

In `~/durabo-platform/layers.json`, in de lijst `lagen`, na laag 6. Neem de veldnamen exact over van laag 6 in datzelfde bestand (`nr`, `naam`, `repo`, `bewijs`, `tests`) — voeg geen nieuwe velden toe:

```json
{
  "nr": 7,
  "naam": "Waarneming (wat elke agentrun deed)",
  "repo": "kit",
  "bewijs": ["waarneming.py"],
  "tests": ["test_waarneming.py"]
}
```

Staat `kit` niet in `repos`, voeg dan toe: `"kit": "~/ai-layer-kit"`.

- [ ] **Step 4: Draai de test tot hij slaagt**

Run: `cd ~/ai-layer-kit && python3.12 test_waarneming.py`
Expected: `alles goed`

- [ ] **Step 5: Controleer dat de controlekamer laag 7 meet**

Run: `cd ~/ai-layer-kit && python3.12 controlroom.py ~/durabo-platform/layers.json --run --xy`
Expected: één JSON-regel; laag 7 staat erin met een lamp, exitcode 0.

- [ ] **Step 6: Maak de xyOps-jobknoop**

xyOps draait shellplug-jobs op de lokale satelliet. Volg het patroon van de bestaande events in `xyops_setup.py` (`Controlekamer · meet (elk kwartier)`) en maak er één bij, titel **`Controlekamer · runs`**, script:

```bash
cd ~/ai-layer-kit && python3.12 controlroom.py ~/durabo-platform/layers.json --runs > /tmp/runs.html && echo "runs gemeten"
```

Trigger: handmatig (`{"type":"manual"}`) — een run-overzicht hoeft geen klok, je kijkt ernaar als er een agent heeft gedraaid.

Vallen die al gemeten zijn en die je hier weer tegenkomt: de API-sleutel moet **Administrator** zijn of `params.script` wordt stil vervangen door de placeholder; een event zonder trigger wordt geweigerd; en `update_event` strijkt `type: "workflow"` eraf — een workflow vervang je (delete + create), een gewoon event mag je bijwerken.

Controleer met:

```bash
KEY=$(python3 -c "import json,pathlib;print(json.load(open(pathlib.Path.home()/'.config/ai-layer-kit/xyops.json'))['api_key'])")
curl -fsS -H "X-API-Key: $KEY" http://127.0.0.1:5522/api/app/get_events/v1 | python3 -m json.tool | grep -A2 'Controlekamer · runs'
```

- [ ] **Step 7: Commit**

```bash
cd ~/durabo-platform
git add layers.json
git commit -m "Laag 7: waarneming — elke agentrun wordt gemeten aan zijn transcript"
cd ~/ai-layer-kit
git add test_waarneming.py
git commit -m "Waarneming: laag 7 staat in het manifest"
```

---

## Wat deze fase bewust niet doet

- **Geen opslag.** Geen OpenObserve, geen database, geen retentie. Heroverwegen zodra deze weergave te dun blijkt, of zodra een tweede machine logs maakt.
- **Geen alarm.** xyOps alarmeert al op `grenzen_rood` en `ketens_intact`; een rode run is geen incident, het is iets om te lezen.
- **Geen tokentellingen.** `message.usage` staat in het transcript, maar kosten sturen hier geen enkel besluit.
