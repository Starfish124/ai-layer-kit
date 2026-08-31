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
from pathlib import Path

PROJECTS = Path.home() / ".claude/projects"
SCHRIJFTOOLS = ("Write", "Edit", "NotebookEdit")


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
    return sorted(uit.values(), key=lambda w: w["gestart"] or "")
