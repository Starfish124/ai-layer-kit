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
