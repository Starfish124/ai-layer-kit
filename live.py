"""Wat er nú gebeurt: één stroom feiten voor het canvas.

Geen dashboardlogica, geen oordeel — alleen gebeurtenissen die ergens meetbaar
zijn: een agent die in een worktree van Vibe Kanban aan een systeem werkt, een
meting die klaar is, een schakel die aan een hash-keten is toegevoegd, een job
in xyOps. Het canvas kleurt ermee; de waarheid blijft bij `meet.py`.

Alles hier is pollen, geen inkomende webhooks: één bestand, geen extra deuren.
`ponytail:` 5 s / 15 s poll-intervallen; een echte push komt pas als dat te traag
blijkt te zijn.

    python3.12 live.py ~/durabo-platform/layers.json     # print gebeurtenissen
"""

import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import meet

VK_DB = Path.home() / "Library/Application Support/ai.bloop.vibe-kanban/db.v2.sqlite"
EVENTS = Path.home() / ".config/ai-layer-kit/events.jsonl"
XYOPS = Path.home() / ".config/ai-layer-kit/xyops.json"
AUDIT = Path.home() / "durabo-audit"


def noteer(soort, tekst, **rest):
    """Eén regel in events.jsonl — zo melden --xy en ?run=1 dat er gemeten is."""
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "soort": soort,
                            "tekst": tekst, **rest}, ensure_ascii=False) + "\n")


# ── Vibe Kanban ───────────────────────────────────────────────────────────────

def _modules_in(worktree, modules):
    """Welke systeem-modules raakt deze worktree: git diff t.o.v. main, alleen .py."""
    try:
        r = subprocess.run(["git", "diff", "--name-only", "main...HEAD"], cwd=worktree,
                           capture_output=True, text=True, timeout=10)
        s = subprocess.run(["git", "status", "--porcelain"], cwd=worktree,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    namen = {Path(l).stem for l in r.stdout.split()} | \
            {Path(l[3:]).stem for l in s.stdout.splitlines() if l.strip()}
    return sorted(namen & modules)


def vk_toestand(m):
    """Per workspace: naam, laatste agent-status, laatste cleanup-status, modules."""
    if not VK_DB.exists():
        return {}
    modules = {s["module"] for s in m.get("systemen", [])}
    repo_naam = {str(p): n for n, p in m["repos"].items()}
    con = sqlite3.connect(f"file:{VK_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rijen = con.execute("""
        select w.id wid, w.name, w.container_ref, w.branch, p.run_reason, p.status, p.exit_code,
               p.started_at, r.path repo_path, r.name repo
        from workspaces w
        join workspace_repos wr on wr.workspace_id = w.id
        join repos r on r.id = wr.repo_id
        left join sessions s on s.workspace_id = w.id
        left join execution_processes p on p.session_id = s.id
        where w.archived = 0 and w.worktree_deleted = 0
        order by p.started_at""").fetchall()
    con.close()
    uit = {}
    for r in rijen:
        w = uit.setdefault(r["name"] or r["branch"], {
            "branch": r["branch"], "agent": None, "cleanup": None, "modules": []})
        if r["run_reason"] == "codingagent":
            w["agent"] = (r["status"], r["exit_code"])
        elif r["run_reason"] == "cleanupscript":
            w["cleanup"] = (r["status"], r["exit_code"])
        if r["container_ref"] and not w["modules"]:
            wt = Path(r["container_ref"]) / r["repo"]
            if wt.is_dir():
                w["modules"] = _modules_in(wt, modules)
    return uit


# ── ketens ────────────────────────────────────────────────────────────────────

def keten_tellingen(m):
    """Aantal schakels per keten. Alleen het getal — nooit de inhoud."""
    uit = {}
    for p in sorted(AUDIT.rglob("*.jsonl")):
        uit[f"audit:{p.parent.name[:8]}/{p.stem}"] = sum(1 for _ in p.open(encoding="utf-8"))
    gem = AUDIT / "gemini" / "ledger.jsonl"
    for p in sorted((AUDIT / "gemini").glob("*.jsonl")) if (AUDIT / "gemini").is_dir() else []:
        uit[f"gemini:{p.stem}"] = sum(1 for _ in p.open(encoding="utf-8"))
    return uit


# ── xyOps ─────────────────────────────────────────────────────────────────────

def xyops_jobs():
    """Actieve jobs in xyOps, als er een sleutel is. Anders niets — geen fout."""
    if not XYOPS.exists():
        return None
    cfg = json.loads(XYOPS.read_text())
    req = urllib.request.Request(f"{cfg['url']}/api/app/get_active_jobs/v1",
                                 headers={"X-API-Key": cfg["api_key"]})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=5).read())
    except Exception:
        return None
    jobs = d.get("jobs") or d.get("data") or {}
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return {j.get("id"): (j.get("event_title") or j.get("title") or j.get("event"),
                          j.get("state") or j.get("status")) for j in jobs}


# ── de stroom ─────────────────────────────────────────────────────────────────

def events(manifest_pad, overrides=None, interval=5.0):
    """Generator van gebeurtenis-dicts; blokkeert, yield bij verandering."""
    m = meet.laad(manifest_pad, overrides)
    vk_prev, ket_prev, xy_prev = {}, None, None
    ev_pos = EVENTS.stat().st_size if EVENTS.exists() else 0
    tik = 0
    while True:
        # 1. metingen en andere genoteerde feiten
        if EVENTS.exists() and EVENTS.stat().st_size > ev_pos:
            with EVENTS.open(encoding="utf-8") as f:
                f.seek(ev_pos)
                for regel in f:
                    try:
                        yield json.loads(regel)
                    except ValueError:
                        pass
                ev_pos = f.tell()

        # 2. Vibe Kanban
        vk = vk_toestand(m)
        for naam, w in vk.items():
            oud = vk_prev.get(naam, {})
            for mod in w["modules"] or [None]:
                if w["agent"] != oud.get("agent") and w["agent"]:
                    st, code = w["agent"]
                    yield {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "soort": "vk", "module": mod,
                           "ok": None if st == "running" else code == 0,
                           "tekst": f"{naam}: agent {'bouwt' if st == 'running' else st}"}
                if w["cleanup"] != oud.get("cleanup") and w["cleanup"]:
                    st, code = w["cleanup"]
                    yield {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "soort": "vk", "module": mod,
                           "ok": None if st == "running" else code == 0,
                           "tekst": f"{naam}: poort (--check) "
                                    f"{'draait' if st == 'running' else ('groen' if code == 0 else 'ROOD')}"}
        vk_prev = vk

        # 3. ketens (elke 15 s)
        if tik % 3 == 0:
            ket = keten_tellingen(m)
            if ket_prev is not None:
                for k, n in ket.items():
                    if n != ket_prev.get(k):
                        yield {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "soort": "keten",
                               "keten": k, "tekst": f"{k}: {n} schakels"}
            ket_prev = ket

            # 4. xyOps
            xy = xyops_jobs()
            if xy is not None and xy != xy_prev:
                for jid, (titel, staat) in xy.items():
                    if (xy_prev or {}).get(jid) != (titel, staat):
                        yield {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "soort": "xyops",
                               "tekst": f"xyOps · {titel}: {staat}"}
                xy_prev = xy
        tik += 1
        time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for e in events(sys.argv[1]):
        print(json.dumps(e, ensure_ascii=False), flush=True)
