# AI-engineer rails: waarneming, eval-poort, bouwgraaf

Datum: 2026-08-31 · Status: vastgesteld, nog niet gebouwd

## Waarom

Vier gemeten pijnpunten uit de bouw van systeem 1–8 (28 aug 2026):

1. **Blinde agentruns.** De mislukte run van systeem 5 staat in
   `~/.claude/projects/…worktrees-0b6d-systeem-5-prijsc…/fe7f6918….jsonl`: 487 KB,
   29 assistantbeurten, 8×Read, 7×Bash, **1×Write**. Eén bestand geschreven, toen dood.
   Dat getal verklaart waarom 5/6/7 met de hand zijn afgemaakt — en het lag er al.
2. **Zwakke poort.** `--check` toetst grenzen, vreemde permissies en rode tests. Niet of de
   opdracht is gehaald. Een handmatige afronding liet de dragende test
   ("geen waarde wordt verzonnen") weg; de poort zag niets.
3. **Geen hervatting.** Systeem 8 gaf nul code bij poging 1; poging 2 was handwerk.
4. **Geen herhaalbaarheid.** De briefs `taak-systeem{4..8}.md` bestaan niet meer — niet in `~`,
   niet in `/tmp`, niet in een repo. Vijf van de acht systemen zijn gebouwd uit instructies
   die weg zijn.

## Wat er niet gebouwd wordt, en waarom

- **OpenObserve.** Geen enkele release van v0.91.0 t/m v1.0.0-rc1 heeft GitHub-assets; geen
  brew-formule. Distributie is Docker of een Rust-bron-build. Deze Mac heeft geen
  docker/colima/podman en geen cargo, en de schijf is een terugkerende crisis (2,9 GB vrij op
  31 aug 16:2x, 11 GB een half uur later). **Heroverwegen zodra** de JSONL-weergave uit fase 1
  te dun blijkt, óf zodra er meer dan één machine logs produceert.
- **Dev/Test/Prod-promotie** (foundry-cicd). Er zijn hier twee sporten: worktree → main.
  Er wordt nog niets naar een Durabo-omgeving uitgerold. De derde sport komt als dat gebeurt.
- **LLM-as-judge in de poort.** Hoofdstuk 11 van het voorstel: *"het model rekent nooit en
  verzint nooit een feit."* Een modeloordeel als merge-poort zet precies daar een
  onnaleesbaar oordeel neer waar de fabriek naleesbaarheid belooft. Evals zijn code.
- **RAG-Kitchen + vectordatabase.** Horen bij systeem 9 (Kennis), dat op laag 1 wacht.
  Apart traject, eigen spec.

## Fase 1 — laag 7 · Waarneming (`waarneming.py` in de kit)

Geen opslag, geen daemon. `live.py` opent VK's `db.v2.sqlite` al; dit breidt dat uit.

**Meet per run**, door de workspace te koppelen aan zijn Claude Code-transcript
(`~/.claude/projects/<gecodeerd worktree-pad>/*.jsonl`): duur, aantal beurten, tool-histogram,
geschreven bestanden, `--check`-exitcode, mergetoestand.

**Rood als** (elk vangt iets dat echt is gebeurd):
- 0 Writes in de run — systeem 8, poging 1;
- `--check` heeft nooit gedraaid;
- een `def test_` die in main's versie van het bestand staat en in de branch niet — het gat
  waardoor de dragende test verdween.

**Toont zich** op `/runs` in de controlekamer, als één xyOps-jobknoop, en als `laag 7` in
`layers.json` (grens vóór code).

**Test:** `test_waarneming.py` plant elk van de drie rode gevallen in een wegwerp-worktree en
eist rood; en één schone run en eist groen.

## Fase 2 — de eval-poort in `check()`

Bestaat al half: alle 8 modules verklaren `UITKOMSTEN`, alle 8 hebben `*_fixtures.py`, en
alle 8 hebben een herkomsttest — onder **acht verschillende namen**
(`test_geen_enkel_veld_wordt_verzonnen`, `test_geen_enkele_cel_wordt_verzonnen`, …,
`test_de_royalty_is_een_naleesbare_vermenigvuldiging`, want dat systeem rékent). Die
inconsistentie is waarom hem weglaten onopgemerkt bleef.

Drie regels erbij, geen nieuw bestandsformaat:

1. **`bewijs_test` per systeem in `layers.json`** — één veld dat de dragende test noemt, bv.
   `"test_royalty.py::test_de_royalty_is_een_naleesbare_vermenigvuldiging"`. De poort eist dat
   hij bestaat én slaagt. Hernoemd, verwijderd of rood → rood.
2. **Uitkomstdekking** — elke letterlijke string in `UITKOMSTEN` van een module moet in het
   testbestand van die module voorkomen (`ast`, stringconstanten). Een verklaarde uitkomst die
   niemand toetst → rood.
3. **Testregressie** — een `def test_` die in main staat en in de branch weg is → rood.

Scope blijft als nu: alleen de overschreven repo's, zodat `test_entra` (heeft `az`) geen merge
blokkeert.

**Test:** `test_evalpoort.py` — per regel één geplante fout die rood moet worden, plus een
schone repo die groen blijft.

## Fase 3 — de bouwgraaf (LangGraph, in `~/glassbox-agents`)

ADR-002 wees orkestratie-met-model al toe aan `glassbox-agents` ("glass-box, gelogd, mens in de
lus"). Daar komt hij, in Python. De 12 Durabo-systemen blijven standaardbibliotheek.

**Knopen:** `brief` → `werkbank` (VK-workspace) → `agent` (Claude Code in de worktree) →
`poort` (`--check` + fase 2) → `merge` | `hervat`. De rand `poort → hervat` citeert de
mislukking letterlijk in de herstelbrief; `hervat → agent` gebruikt
`claude --resume <session-id>` uit het transcript dat fase 1 al koppelt.

**De brief wordt een artefact:** `briefs/<module>.md`, in de repo gecommit, vóór de run —
dezelfde regel als de grens. Dit dicht pijnpunt 4.

**Drift, ingeperkt in plaats van weggeredeneerd.** De checkpointer draagt alléén brief,
pogingnummer en geciteerde mislukkingen. Waarheid over *wat gebouwd is* blijft VK's sqlite,
git en `layers.json`; elke knoop leest die werkelijkheid opnieuw bij binnenkomst.
`test_bouwer.py` eist dat de checkpointer nergens als gezag wordt gelezen.

**Zichtbaar op drie gemeten vlakken** (geen enkele met de hand getekend, dus ADR-005 houdt):

1. **`/flow`** — topologie uit `compiled.get_graph()` (aan het levende object gevraagd, niet uit
   een bestand), posities `f(laag, rij)` per ADR-007, knopen live gekleurd uit de `/events`-SSE.
2. **xyOps Workflows** — geschiedenis en planning; xyOps draait de graaf en leest wat hij
   print (ADR-006).
3. **`/runs`** uit fase 1 — het spoor achter elke knoop die je aanklikt.

**ADR-008** legt dit vast: waarom LangGraph hier wél mag terwijl ADR-002 een model in de
rekenkunde verbiedt (dit orkestreert de bouw, niet de rekenkunde), het driftrisico, en de
inperking.

## Volgorde

Fase 1 → 2 → 3. Fase 3 heeft 1 en 2 nodig: de graaf hervat op het transcript dat 1 koppelt, en
zijn poortknoop is de regelset van 2.
