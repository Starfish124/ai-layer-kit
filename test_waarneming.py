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
