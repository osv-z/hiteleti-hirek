# Hitéleti hírek

Minden reggel letölti a hazai és nemzetközi katolikus hírportálok RSS-csatornáit (az elmúlt 2 napból), az azonos eseményről
szóló cikkeket egy hírbe vonja össze, a több forrásban szereplőket előre sorolja, és az
eredményt a `docs/hirek.json` fájlba menti. A GitHub Pages ezt ingyenesen elérhetővé teszi
az app számára. A nemzetközi hírek címét és leadjét a Gemini API fordítja magyarra
(csak fordít, nem ír újat). A források listája angolul marad.

## Beállítás

1. **Gemini API-kulcs** (csak a fordításhoz, ingyenes): https://aistudio.google.com → „Get API key”.
   A repóban: Settings → Secrets and variables → Actions → New repository secret,
   név: `GEMINI_API_KEY`. Kulcs nélkül is működik, csak a nemzetközi hírek angolul maradnak.
2. **GitHub-repó:** töltsd fel az összes fájlt (a `.github` mappát is). A repónak nyilvánosnak
   kell lennie, hogy az ingyenes GitHub Pages működjön.
3. **GitHub Pages:** Settings → Pages → Source: „Deploy from a branch”,
   Branch: `main`, mappa: `/docs`.
4. **Első futtatás:** Actions fül → „Hitéleti hírek” → Run workflow.

Az app címe: `https://<felhasznalonev>.github.io/<repo-neve>/`

## Az app telepítése a telefonra

- **Android (Chrome):** nyisd meg a címet, majd koppints a „Telepítés” gombra.
- **iPhone (Safari):** Megosztás gomb → „Főképernyőhöz adás”.

Ha módosítod az appot, a `docs/sw.js` elején növeld a `VERZIO` számát.

## Helyi tesztelés

```bash
pip install -r requirements.txt
python hirosszefoglalo.py                        # fordítás nélkül
GEMINI_API_KEY=a_kulcsod python hirosszefoglalo.py   # fordítással
cd docs && python -m http.server 8000            # majd: http://localhost:8000
```

## Testreszabás

- Források: `HAZAI_FORRASOK` és `NEMZETKOZI_FORRASOK` a szkript elején.
  Ha egy forrás 0 cikket ad, valószínűleg megváltozott az RSS-címe.
- Betűméret: a `docs/index.html`-ben a `html { font-size: 118%; ... }` érték
  (nagyobb szám = nagyobb betű).
- Hírek száma: `HAZAI_DB`, `NEMZETKOZI_DB`.
- Csoportosítás érzékenysége: `HASONLOSAG` (kisebb érték = több cikket von össze).

## Megjegyzések

- A forráslista kiegyensúlyozott: a nemzetközi források között hivatalos (Vatican News),
  konzervatívabb (CNA, The Pillar) és progresszívebb (National Catholic Reporter, America) lapok is vannak.

- A csoportosítás a címek szavai alapján működik, ezért ha két forrás nagyon eltérő
  szavakkal írja le ugyanazt az eseményt, külön hírként jelenhet meg.
- A fordítás gépi, ezért pontatlan lehet. Ha nem sikerül, a hírek angolul jelennek meg.
- Az ingyenes Gemini-csomag korlátai és adatkezelési feltételei változhatnak.
- A GitHub ütemezett futásai néha 10-30 percet késnek.
- 
