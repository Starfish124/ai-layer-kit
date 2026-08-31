"""Wat een agentrun deed, gemeten aan zijn transcript.

    python3.12 test_waarneming.py
"""

import json
import sqlite3
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


def test_de_mapnaam_resolve_var_symlinks_op_macos():
    # /var is een symlink naar /private/var op macOS; transcriptmap moet dit resolven
    # zodat het matcht met hoe Claude Code de transcriptdirectory noemt.
    # Dit test dat een /var/folders/...-pad geresolved wordt naar -private-var-folders-.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "link"
        link_dir.symlink_to(real_dir)

        # Link pad en resolved pad moeten dezelfde encoding produceren
        # want resolve() brengt beide naar dezelfde echte pad
        encoded_link = str(waarneming.transcriptmap(link_dir, tmp_path))
        encoded_real = str(waarneming.transcriptmap(real_dir, tmp_path))
        assert encoded_link == encoded_real, f"{encoded_link} != {encoded_real}"


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
    con.execute("insert into repos values ('r1','stride-durabo','/repo')")
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


def test_meerdere_sessies_worden_gea_gregeerd_niet_willekeurig_gek_ozen():
    # Test dat aggregeert TWO sessions, met UUIDs die alfabetisch tegengesteld sorteren
    # aan hun chronologische volgorde. De oude code zou willekeurig een kiezen.
    hier = TMP / "vk3"
    hier.mkdir(parents=True, exist_ok=True)
    container = hier / "worktrees"
    worktree = container / "systemen"
    worktree.mkdir(parents=True)
    projects = hier / "projects"

    # Maak twee sessions met UUIDs die tegengesteld sorteren
    # UUID "zzz..." sorteert LATER dan "aaa..." maar we willen het EERSTE chronologisch
    transcript_dir = waarneming.transcriptmap(worktree, projects)
    _transcript(transcript_dir / "zzz-eerste-sessie.jsonl", [
        _beurt("2026-08-28T11:39:00.000Z", [_tool("Write", file_path="bestand1.py")]),
        _beurt("2026-08-28T11:40:00.000Z", [_tool("Write", file_path="bestand2.py")]),
    ])
    _transcript(transcript_dir / "aaa-tweede-sessie.jsonl", [
        _beurt("2026-08-28T11:41:00.000Z", [_tool("Read", file_path="a.py")]),
        _beurt("2026-08-28T11:42:00.000Z", [_tool("Bash", command="ls")]),
    ])
    _vk_db(hier / "db.sqlite", container)

    r = waarneming.runs({"repos": {"systemen": Path("/repo")}},
                        vk_db=hier / "db.sqlite", projects=projects)
    assert len(r) == 1, r
    # Beide sessions moeten gea_gregeerd zijn
    assert r[0]["beurten"] == 4, f"Verwacht 4 beurten (2+2), kreeg {r[0]['beurten']}"
    assert r[0]["sessies"] == 2, f"Verwacht 2 sessies, kreeg {r[0]['sessies']}"
    # Geschreven bestanden uit beide sessions
    assert set(r[0]["geschreven"]) == {"bestand1.py", "bestand2.py"}, \
        f"Verwacht beide bestanden, kreeg {r[0]['geschreven']}"
    # Tools uit beide sessions
    assert r[0]["tools"]["Write"] == 2, f"Verwacht 2 Writes, kreeg {r[0]['tools']}"
    assert r[0]["tools"]["Read"] == 1
    assert r[0]["tools"]["Bash"] == 1


if __name__ == "__main__":
    for naam, fn in sorted(globals().items()):
        if naam.startswith("test_"):
            fn()
    print("alles goed")
