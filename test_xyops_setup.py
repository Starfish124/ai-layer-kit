"""De guard: xyops_setup.py mag niet vanuit een worktree draaien.

Elke job bakt KIT in zijn `cd`, dus draaien vanuit een worktree herschrijft alle
productiejobs naar een tijdelijk pad. Dat is één keer echt gebeurd.

    python3.12 test_xyops_setup.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent


def test_de_hoofdcheckout_mag_draaien():
    """--toon leest alleen; hier mag de guard niet in de weg lopen."""
    r = subprocess.run([sys.executable, "xyops_setup.py", "--toon"], cwd=KIT,
                       capture_output=True, text=True, timeout=60)
    assert "vanuit een worktree" not in r.stderr, r.stderr


def test_een_worktree_wordt_geweigerd():
    """De echte val: dezelfde code, ander pad — en hij moet stoppen vóór hij iets schrijft."""
    tmp = Path(tempfile.mkdtemp(prefix="ai-layer-kit-guard-"))
    wt = tmp / "wt"
    add = subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"],
                         cwd=KIT, capture_output=True, text=True, timeout=60)
    assert add.returncode == 0, add.stderr
    try:
        # De worktree checkt HEAD uit; wij willen de guard toetsen zoals hij NU is,
        # niet zoals hij bij de laatste commit was.
        (wt / "xyops_setup.py").write_text((KIT / "xyops_setup.py").read_text(encoding="utf-8"),
                                           encoding="utf-8")
        r = subprocess.run([sys.executable, "xyops_setup.py", "--toon"], cwd=wt,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode != 0, "de guard liet een worktree door"
        assert "vanuit een worktree" in r.stderr, r.stderr
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=KIT, capture_output=True, timeout=60)


if __name__ == "__main__":
    for naam, fn in sorted(globals().items()):
        if naam.startswith("test_"):
            fn()
    print("alles goed")
