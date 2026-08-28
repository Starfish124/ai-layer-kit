# ai-layer-kit — de controlekamer voor een AI-laag

Eén pagina die **meet** hoe een AI-laag om een Microsoft-omgeving heen ervoor staat:

- **Lagen** — is elke laag van de stack gebouwd, getest, groen (bewijsbestanden + tests)
- **Grenzen per systeem** — wat leest het, met welke Graph-permissie, waar staat de data,
  wat verlaat de tenant; gemeten tegen de code (verboden imports, schrijfwerkwoorden naast
  een netwerk-import, permissies in Entra-scripts die niemand claimt)
- **Tests en ketens** — elke `test_*.py` in elke repo met zijn laatste regel; de hash-ketens
- **Beslissingen** — de ADR-koppen uit `ARCHITECTURE.md`; het enige dat met de hand is geschreven

Python 3.12, alleen standaardbibliotheek. Nederlandse UI.

    python3.12 test_meet.py && python3.12 test_controlroom.py
    python3.12 controlroom.py ~/durabo-platform/layers.json --serve     # http://127.0.0.1:7415
    python3.12 controlroom.py ~/durabo-platform/layers.json --run --html > pagina.html

## Een project aansluiten

Zet een `layers.json` **in de repo van het project** (niet hier) — zie `layers.example.json`.
Repo's mogen overal staan; bewijs- en testpaden zijn relatief aan hun repo. De kit weigert
absolute paden, houdt geen klantdata vast en tekent niets met de hand.

## Wat het bewust niet doet

- Geen dashboards over Azure-telemetrie: die meten Azure-gehoste dingen, en dit draait lokaal.
- Geen diagrammen uit de losse pols: `/graph` in het project tekent de modulekaart uit `ast`.
- Geen model: de pagina rekent niets, `test_controlroom` bewaakt dat.
