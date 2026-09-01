# Begrensde hervatting en geheimen

Datum: 2026-09-01 · Status: vastgesteld, nog niet gebouwd

Amendement op `2026-08-31-ai-engineer-rails-design.md`. Dat blijft staan zoals het is;
dit vult twee gaten en voegt één nachtelijke baan toe. Fase 1 is gebouwd, fase 2 en 3 niet.

## Waarom

De rails-spec tekent de rand `poort → hervat → agent`, maar **noemt geen bovengrens**.
Een lus zonder plafond is hier geen theorie: de EVOLVE-lus gaf $69 uit tegen een kap van $50,
en dat gebeurde omdat de kap op de verkeerde eenheid stond, niet omdat hij ontbrak.

Daarnaast toetst de poort — nu en na fase 2 — nergens of er een sleutel in het diff staat.
`ai-discovery-durabo` is een **publieke** repo met persoonsgegevens; `stride-console` en
`stride-seo-engine` worden door drie sessies tegelijk bewerkt. `gitleaks` staat niet
geïnstalleerd.

## Wat dit wijzigt aan de rails-spec

- Fase 3, rand `poort → hervat`: krijgt een plafond en een uitzondering (regel 1 en 2).
- Fase 2, `check()`: krijgt één regel erbij (regel 3) en één (regel 4).
- Ongewijzigd: de afwijzing van LLM-as-judge in de poort. **Evals blijven code.** Een
  promptfoo/DeepEval-poort is overwogen op 1 sep 2026 en opnieuw afgewezen, om de reden die
  er al stond: een modeloordeel als merge-poort is niet naleesbaar.
- Ongewijzigd: xyOps draait de graaf en leest wat hij print (ADR-006). De lus zit in de graaf,
  niet in xyOps. Een `Repeat`-controller met `max gelijktijdig = 1` kán een lus nabootsen, maar
  dan staat de hervattingslogica op twee plekken; dat is overwogen en verworpen.

## Regel 1 — de hervat-rand is begrensd

De checkpointer draagt al brief, pogingnummer en geciteerde mislukkingen. Daar komt bij:
`eerste_poging_op` (ISO-tijd). De rand `poort → hervat` vuurt alleen als **beide** gelden:

    pogingen < POGINGEN          # 3
    nu - eerste_poging_op < WANDKLOK   # 45 min

Anders gaat de taak naar `geparkeerd`: een xyOps-ticket met de laatste mislukking, en de
workspace blijft staan zoals hij is. Geen stille afbreking.

Beide grenzen zijn nodig. Alleen pogingen tellen laat één agentrun die twee uur hangt nooit
aflopen; alleen de wandklok laat drie snelle identieke mislukkingen alle tijd opmaken.

**Uitzondering:** een poging die strandt op *geen model* — `claude` niet bereikbaar, tokens op —
telt **niet** als poging en verhoogt de teller niet. Anders parkeert een storing bij de
leverancier gezonde taken om de verkeerde reden. De wandklok blijft wel lopen.

`POGINGEN` en `WANDKLOK` staan in `layers.json` naast de systemen, niet in de code: de juiste
waarde is gemeten, niet bedacht, en systeem 9 (Kennis) zal een ander getal willen dan systeem 2.

## Regel 2 — geheimen nemen de hervat-rand nooit

`gitleaks git --log-opts="<doeltak>..HEAD"` draait in `check()`, over de commits die de
werkbank aan de doeltak toevoegt.

Niet `protect --staged`: de agent commit zelf, dus op het moment dat de poort draait staat er
niets meer gestaged en zou de scan altijd schoon zijn.

Een vondst is **rood en niet-hervatbaar**: de taak gaat direct naar `geparkeerd`, ongeacht
resterende pogingen. Een lek wordt niet opgelost door code te herschrijven maar door de sleutel
te roteren, en dat is mensenwerk buiten de repo. Een agent laten hervatten stapelt alleen
commits bovenop een sleutel die nog leeft.

De poort meldt *dat* er iets gevonden is en waar — nooit de waarde zelf, ook niet in het
jobrapport, ook niet in `last-run`. xyOps' jobuitvoer is leesbaar voor iedereen met toegang tot
de fabriek.

## Regel 3 — de bouw start

Een repo met een `dev_server_script` in VK moet ermee opstarten. De poort start hem, wacht tot
de netwerkpoort luistert of tot een time-out, en dooft hem. Start hij niet: rood. Die roodheid
is hervatbaar zodra de rand uit fase 3 bestaat; tot die tijd is het een rode poort als elke
andere.

Dit vangt wat de drie regels van fase 2 niet vangen: tests die groen zijn terwijl de
configuratie of de opstartvolgorde stuk is. Durabo heeft dit script al
(`controlroom.py … --serve --port 7416`).

## Nachtelijke baan — de machine, niet de taak

Eén xyOps-baan per nacht, buiten de poort om, want dit gaat over deze Mac en niet over een diff:

- `uvx mcp-scan@latest` over de MCP-servers die in Claude Code hangen (tool poisoning, rug pulls).
  Er hangen er ~15, waarvan een deel van derden.
- `trufflehog` over de volledige geschiedenis van de repo's, niet alleen het diff.

Rood hier opent een ticket. Het blokkeert geen merge — een nachtelijke bevinding hoort niet
morgenochtend een werkbank te gijzelen.

## Test

`test_hervatting.py`, met dezelfde truc die `injectie.py` al gebruikt: de lus krijgt zijn poort
en zijn agent als parameter, zodat de toestandsmachine te draaien is zonder een token uit te
geven of xyOps te starten.

- `POGINGEN` bereikt → geparkeerd, agent niet meer aangeroepen
- `WANDKLOK` verstreken terwijl er nog pogingen over zijn → geparkeerd
- geen-model → teller staat stil, wandklok loopt door
- een geplante sleutel in het diff → geparkeerd bij poging 1, agent nul keer aangeroepen
- schone werkbank → groen, agent nul keer aangeroepen

Dat vierde geval is de dragende test van dit amendement.

## Volgorde

Regel 2 eerst, en los van de rest: `gitleaks` installeren en één keer over alle repo's halen.
Dat heeft waarde vóór er een graaf bestaat. Daarna regel 3, dan de nachtelijke baan; regel 1
komt met fase 3, want daar bestaat de rand pas.
