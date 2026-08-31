"""Wat een agentrun deed, gemeten aan zijn transcript.

    python3.12 test_waarneming.py
"""

import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import controlroom
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


def test_meerdere_sessies_worden_geaggregeerd_niet_willekeurig_gekozen():
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
    # Beide sessions moeten geaggregeerd zijn
    assert r[0]["beurten"] == 4, f"Verwacht 4 beurten (2+2), kreeg {r[0]['beurten']}"
    assert r[0]["sessies"] == 2, f"Verwacht 2 sessies, kreeg {r[0]['sessies']}"
    # Geschreven bestanden uit beide sessions
    assert set(r[0]["geschreven"]) == {"bestand1.py", "bestand2.py"}, \
        f"Verwacht beide bestanden, kreeg {r[0]['geschreven']}"
    # Tools uit beide sessions
    assert r[0]["tools"]["Write"] == 2, f"Verwacht 2 Writes, kreeg {r[0]['tools']}"
    assert r[0]["tools"]["Read"] == 1
    assert r[0]["tools"]["Bash"] == 1
    # duur_s moet spanning van eerste tot laatste timestamp ACROSS all sessions: 11:39:00 tot 11:42:00 = 180 seconden
    assert r[0]["duur_s"] == 180.0, f"Verwacht 180.0 seconden (11:39 tot 11:42), kreeg {r[0]['duur_s']}"


def test_null_agent_working_dir_geeft_geen_exception():
    # Constraint: NULL agent_working_dir mag geen TypeError geven; run komt grijs terug
    hier = TMP / "vk4"
    hier.mkdir(parents=True, exist_ok=True)
    container = hier / "worktrees"
    worktree = container / "systemen"
    worktree.mkdir(parents=True)

    # Voeg rij in met NULL agent_working_dir
    con = sqlite3.connect(hier / "db.sqlite")
    con.executescript(SCHEMA)
    con.execute("insert into repos values ('r1','stride-durabo','/repo')")
    con.execute("insert into workspaces values ('w1','Systeem Test','vk/test',?,0,0)",
                (str(container),))
    con.execute("insert into workspace_repos values ('w1','r1')")
    con.execute("insert into sessions values ('s1','w1',NULL)")  # NULL agent_working_dir
    con.execute("insert into execution_processes values "
                "('p1','s1','codingagent','completed',0,'2026-08-28T11:39:00Z')")
    con.commit()
    con.close()

    r = waarneming.runs({"repos": {"systemen": Path("/repo")}},
                        vk_db=hier / "db.sqlite", projects=hier / "projects")
    assert len(r) == 1, r
    # Run moet grijs zijn (geen exception), met None waarden voor transcript-afhankelijke velden
    assert r[0]["worktree"] is None, f"Verwacht worktree=None, kreeg {r[0]['worktree']}"
    assert r[0]["transcript"] is None, r[0]
    assert r[0]["beurten"] is None, r[0]
    assert r[0]["sessies"] == 0, f"Verwacht sessies=0, kreeg {r[0]['sessies']}"


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


def _git_tak(repo, tak, bestanden):
    """Een tak in deze repo — en nadrukkelijk géén worktree ervoor."""
    subprocess.run(["git", "checkout", "-q", "-b", tak], cwd=repo, check=True)
    for naam, inhoud in bestanden.items():
        (repo / naam).write_text(inhoud, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", tak], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    return tak


def test_een_tak_die_niets_toevoegt_is_rood():
    """Regel 1 meet de diff van de tak, niet het aantal Writes in het transcript."""
    repo = _git_repo(TMP / "leegtak" / "repo", {"a.py": "x = 1\n"})
    subprocess.run(["git", "branch", "vk/leeg"], cwd=repo, check=True)
    run = {"geschreven": [], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/leeg", "worktree": None, "repo_pad": str(repo), "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert any("geen enkel bestand" in r for r in rood), rood
    assert gemeten["schreef"] is True, gemeten


def test_een_agent_die_met_een_heredoc_schrijft_is_niet_rood():
    """`cat > bestand <<EOF` laat geen Write achter in het transcript, wel een diff."""
    repo = _git_repo(TMP / "heredoc" / "repo", {"a.py": "x = 1\n"})
    _git_tak(repo, "vk/hd", {"b.py": "y = 2\n"})
    run = {"geschreven": [], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/hd", "worktree": None, "repo_pad": str(repo), "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert rood == [], rood
    assert gemeten == {"schreef": True, "poort": True, "testregressie": True}, gemeten


def test_een_gemergede_tak_met_writes_in_het_transcript_is_groen():
    """De tak zit in main, dus `main...tak` is leeg — dat is geslaagd werk, geen niets.

    Systeem 3, 4 en 8 zijn precies dit geval: hun tak is een voorouder van main.
    """
    repo = _git_repo(TMP / "gemerged" / "repo", {"a.py": "x = 1\n"})
    subprocess.run(["git", "branch", "vk/gemerged"], cwd=repo, check=True)
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "main loopt door"], cwd=repo, check=True)
    assert waarneming._gewijzigd(repo, "main...vk/gemerged") == [], "de tak zit in main"
    run = {"geschreven": ["a.py", "b.py"], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/gemerged", "worktree": None, "repo_pad": str(repo),
           "transcript": "/x/s.jsonl"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert rood == [], rood
    assert gemeten == {"schreef": True, "poort": True, "testregressie": True}, gemeten


def test_een_testbestand_dat_de_tak_nooit_zag_is_geen_regressie():
    """main is doorgelopen: test_nieuw.py is er later bijgekomen. Niemand deed iets fout.

    Een test die uit een bestand verdwijnt dat beide refs kennen, is dat wél.
    """
    repo = _git_repo(TMP / "jongertak" / "repo", {
        "test_gedeeld.py": "def test_blijft():\n    pass\ndef test_valt_weg():\n    pass\n"})
    _git_tak(repo, "vk/oud", {"test_gedeeld.py": "def test_blijft():\n    pass\n"})
    (repo / "test_nieuw.py").write_text("def test_later_toegevoegd():\n    pass\n",
                                        encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "main krijgt er een test bij"], cwd=repo, check=True)
    weg = waarneming._verdwenen_tests(repo, "vk/oud")
    assert weg == ["test verdwenen t.o.v. main: test_valt_weg in test_gedeeld.py"], weg


def test_een_tak_die_een_testbestand_weggooit_is_wel_rood():
    repo = _git_repo(TMP / "weggegooid" / "repo", {
        "test_prijs.py": "def test_a():\n    pass\ndef test_b():\n    pass\n"})
    subprocess.run(["git", "checkout", "-q", "-b", "vk/sloop"], cwd=repo, check=True)
    subprocess.run(["git", "rm", "-q", "test_prijs.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "weg ermee"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    weg = waarneming._verdwenen_tests(repo, "vk/sloop")
    assert weg == ["testbestand verwijderd op de tak: test_prijs.py (2 tests bij het aftakken)"], weg


def test_een_poort_die_nooit_draaide_is_rood():
    run = {"geschreven": ["a.py"], "cleanup": None, "status": "completed",
           "branch": None, "worktree": None, "repo_pad": None, "transcript": "x"}
    rood, _ = waarneming.oordeel(run, {})
    assert any("poort" in r for r in rood), rood


def test_een_poort_die_draaide_en_afkeurde_is_rood():
    """`--check` heeft gedraaid en het werk afgewezen: exit 1 is geen groen."""
    run = {"geschreven": ["a.py"], "cleanup": ("completed", 1), "status": "completed",
           "branch": None, "worktree": None, "repo_pad": None, "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {})
    assert any("exit 1" in r for r in rood), rood
    assert gemeten["poort"] is True, gemeten


def test_een_run_die_nog_draait_is_grijs_niet_groen():
    for status in ("running", None):
        run = {"geschreven": ["a.py"], "cleanup": None, "status": status,
               "branch": None, "worktree": None, "repo_pad": None, "transcript": "x"}
        rood, gemeten = waarneming.oordeel(run, {})
        assert not any("poort" in r for r in rood), (status, rood)
        assert gemeten["poort"] is not True, (status, gemeten)


def test_een_verdwenen_test_op_een_tak_zonder_worktree_is_rood():
    """De worktree bestaat niet — vijf van de zes bestaan niet meer — de tak wel.

    En de agent schreef prijs.py, geen enkel test_-bestand: regel 3 mag zich niet
    beperken tot wat de agent aanraakte.
    """
    repo = _git_repo(TMP / "regressie" / "repo", {
        "prijs.py": "prijs = 1\n",
        "test_prijs.py": "def test_geen_enkele_waarde_wordt_verzonnen():\n    pass\n"
                         "def test_iets_anders():\n    pass\n"})
    _git_tak(repo, "vk/0b6d-systeem-5", {
        "prijs.py": "prijs = 2\n",
        "test_prijs.py": "def test_iets_anders():\n    pass\n"})
    run = {"geschreven": ["prijs.py"], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/0b6d-systeem-5", "worktree": "/bestaat/allang/niet/meer",
           "repo_pad": str(repo), "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert any("test_geen_enkele_waarde_wordt_verzonnen" in x for x in rood), rood
    assert gemeten["testregressie"] is True, gemeten


def test_een_nieuw_bestand_is_iets_anders_dan_git_die_niets_kon_zeggen():
    """Nieuw bestand = bevinding. Onleesbaar = grijs. Samenvallen maakt stil groen."""
    repo = _git_repo(TMP / "sentinel" / "repo", {"a.py": "x = 1\n"})
    assert waarneming._lees(repo, "main", "a.py") == "x = 1\n"
    assert waarneming._lees(repo, "main", "nieuw.py") is None
    assert waarneming._lees(repo, "vk/bestaat-niet", "a.py") is waarneming.ONLEESBAAR
    geen_repo = TMP / "sentinel" / "geen-git"
    geen_repo.mkdir(parents=True, exist_ok=True)
    assert waarneming._lees(geen_repo, "main", "a.py") is waarneming.ONLEESBAAR


def test_een_tak_die_niet_meer_bestaat_is_grijs_niet_groen():
    repo = _git_repo(TMP / "grijzetak" / "repo", {"a.py": "x = 1\n"})
    run = {"geschreven": ["a.py"], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/weg", "worktree": None, "repo_pad": str(repo), "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert rood == [], rood
    assert gemeten["testregressie"] == "tak vk/weg bestaat niet meer", gemeten


def test_een_run_zonder_gekoppelde_repo_is_grijs_niet_groen():
    run = {"geschreven": ["a.py"], "cleanup": ("completed", 0), "status": "completed",
           "branch": "vk/x", "worktree": None, "repo_pad": None, "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {})
    assert rood == [], rood
    assert [v for v in gemeten.values() if v is not True], gemeten


def test_de_repo_wordt_op_pad_gekoppeld_niet_op_naam():
    """VK noemt hem stride-durabo, layers.json noemt hem systemen — pad is de koppeling."""
    hoofd = _git_repo(TMP / "koppel" / "hoofd", {"test_a.py": "def test_a():\n    pass\n"})
    run = {"repo_pad": str(hoofd), "repo": "stride-durabo"}
    assert waarneming._hoofdrepo(run, {"systemen": hoofd}) is not None
    assert waarneming._hoofdrepo({"repo_pad": "/bestaat/niet"}, {"systemen": hoofd}) is None


def test_een_schone_run_is_groen():
    repo = _git_repo(TMP / "schoon" / "repo", {"test_prijs.py": "def test_a():\n    pass\n"})
    _git_tak(repo, "vk/schoon", {"test_prijs.py": "def test_a():\n    pass\n"
                                                  "def test_b():\n    pass\n"})
    run = {"geschreven": ["test_prijs.py"], "cleanup": ("completed", 0),
           "status": "completed", "branch": "vk/schoon", "worktree": None,
           "repo_pad": str(repo), "transcript": "x"}
    rood, gemeten = waarneming.oordeel(run, {"systemen": repo})
    assert rood == [], rood
    assert gemeten == {"schreef": True, "poort": True, "testregressie": True}, gemeten


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


def test_laag_zeven_staat_in_het_manifest():
    manifest = Path.home() / "durabo-platform/layers.json"
    if not manifest.exists():
        print("overgeslagen: ~/durabo-platform/layers.json staat niet op deze machine")
        return
    m = json.loads(manifest.read_text(encoding="utf-8"))
    laag = [l for l in m["lagen"] if l["nr"] == 7]
    assert laag, "laag 7 ontbreekt in layers.json"
    assert "waarneming.py" in json.dumps(laag[0]), laag[0]


def test_een_ontbrekende_vk_database_is_geen_nul_runs():
    """Ontbrekend gereedschap moet zeggen dat het niet kan meten, niet 'leeg'."""
    assert waarneming.runs({}, vk_db=TMP / "bestaat-niet.sqlite") is None
    h = controlroom.runs_html(None)
    assert "niet gevonden" in h, h
    assert "Geen runs in Vibe Kanban" not in h, h


def test_de_pagina_toont_grijs_met_reden_als_een_regel_niet_draaide():
    rijen = [{"workspace": "Systeem 5", "branch": "vk/s5", "status": "completed",
              "exit_code": 0, "gestart": "2026-08-28T11:39:00Z", "duur_s": 60.0,
              "beurten": 29, "tools": {}, "geschreven": ["prijs.py"],
              "cleanup": ("completed", 0), "transcript": "/x", "rood": [],
              "gemeten": {"schreef": True, "poort": True,
                          "testregressie": "tak vk/s5 bestaat niet meer"}}]
    h = controlroom.runs_html(rijen)
    assert "kaart grijs" in h, h
    assert "kaart groen" not in h, "een regel die niet draaide mag nooit groen worden"
    assert "tak vk/s5 bestaat niet meer" in h, h


def test_runs_html_ontsnapt_werkruimte_en_tak():
    kwaad = "<script>alert(1)</script>"
    rijen = [{"workspace": kwaad, "branch": kwaad, "status": "failed",
              "exit_code": 1, "gestart": "2026-08-28T11:39:00Z", "duur_s": 60.0,
              "beurten": 1, "tools": {}, "geschreven": [], "cleanup": None,
              "transcript": "/x/s.jsonl", "rood": []}]
    h = controlroom.runs_html(rijen)
    assert "<script>alert(1)</script>" not in h, "html moet ontsnapt zijn, niet ruw"
    assert "&lt;script&gt;" in h, "de ontsnapte vorm moet wel op de pagina staan"


if __name__ == "__main__":
    for naam, fn in sorted(globals().items()):
        if naam.startswith("test_"):
            fn()
    print("alles goed")
