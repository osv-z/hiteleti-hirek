#!/usr/bin/env python3
"""
Hitéleti hírek
RSS-csatornák -> csoportosítás és rangsorolás -> (nemzetközi hírek fordítása) -> docs/hirek.json

Az azonos eseményről szóló cikkeket egy hírré vonja össze, és azokat sorolja előre,
amelyekről a legtöbb különböző forrás ír. A szöveg az RSS-ben megadott eredeti cím és lead.
A nemzetközi hírek címét és leadjét a Gemini API fordítja magyarra (csak fordít, nem ír újat).
Ha nincs GEMINI_API_KEY, vagy a fordítás nem sikerül, a hírek angolul maradnak.

Használat:
    python hirosszefoglalo.py
    GEMINI_API_KEY=... python hirosszefoglalo.py     # fordítással
"""

import html
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

# ---------------------------------------------------------------------------
# Beállítások
# ---------------------------------------------------------------------------

# Az RSS-címek változhatnak – ha egy forrás 0 cikket ad, ellenőrizd a címét.
HAZAI_FORRASOK = {
    "Magyar Kurír": "https://www.magyarkurir.hu/rss",
    "Új Ember": "https://ujember.hu/feed/",
    "Vatican News (magyar)": "https://www.vaticannews.va/hu.rss.xml",
    "777": "https://777blog.hu/feed/",
    "Zarándok.ma": "https://zarandok.ma/feed/",
    "Szemlélek": "https://szemlelek.net/feed/",
}

NEMZETKOZI_FORRASOK = {
    "Vatican News": "https://www.vaticannews.va/en.rss.xml",
    "Catholic News Agency": "https://www.catholicnewsagency.com/feed",
    "National Catholic Reporter": ["https://www.ncronline.org/rss.xml", "https://www.ncronline.org/feed"],
    "The Pillar": "https://www.pillarcatholic.com/feed",
    "Catholic Herald": "https://catholicherald.co.uk/feed/",
    "Aleteia": "https://aleteia.org/feed/",
    "UCA News": ["https://www.ucanews.com/rss", "https://www.ucanews.com/feed"],
}

HAZAI_DB = 10            # ennyi hazai hír kerüljön a listába
NEMZETKOZI_DB = 10       # ennyi nemzetközi hír
MAX_CIKK_FORRASONKENT = 25
MAX_ORA = 48             # a hitéleti portálok ritkábban frissülnek, ezért 2 nap
MAX_EGYFORRASOS_FORRASONKENT = 3   # egyetlen forrás ennyi "csak nála szereplő" hírt adhat
HASONLOSAG = 0.4         # ennél nagyobb címhasonlóságnál egy eseménynek számít

MODELL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
API_KULCS = os.environ.get("GEMINI_API_KEY")

FORDITAS_PROMPT = """Fordítsd le magyarra az alábbi angol nyelvű katolikus hírcímeket és rövid leadeket.
Szabályok:
- Csak fordíts, ne adj hozzá, ne hagyj el és ne értelmezz semmit.
- A tulajdonneveket és intézménynevek megszokott magyar alakját használd (pl. Európai Unió),
  a személyneveket hagyd az eredeti írásmódban. Az egyházi kifejezéseknél a magyar katolikus
  szóhasználatot kövesd (pl. Holy See = Szentszék, Pope Leo = Leó pápa, bishop = püspök,
  synod = szinódus, dicastery = dikasztérium).
- A cím maradjon hírcím-stílusú, tömör.
- Az üres leadet hagyd üresen.
A válaszod kizárólag érvényes JSON tömb legyen, pontosan annyi elemmel és ugyanabban a
sorrendben, ahogy a bemenetben szerepelnek: [{"cim": "...", "lead": "..."}]

BEMENET:
__BEMENET__
"""

KIMENET = Path(__file__).resolve().parent / "docs"
IDOZONA = ZoneInfo("Europe/Budapest")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FEJLEC = {"User-Agent": USER_AGENT,
          "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}


# ---------------------------------------------------------------------------
# Hírgyűjtés
# ---------------------------------------------------------------------------

def tisztit(szoveg, max_hossz=320):
    """HTML-címkék és felesleges szóközök eltávolítása, szóhatáron levágás."""
    szoveg = re.sub(r"<[^>]+>", " ", szoveg or "")
    szoveg = html.unescape(szoveg)
    szoveg = re.sub(r"\s+", " ", szoveg).strip()
    if len(szoveg) > max_hossz:
        szoveg = szoveg[:max_hossz].rsplit(" ", 1)[0].rstrip(",.;:–- ") + "…"
    return szoveg


def cikk_ideje(bejegyzes):
    for mezo in ("published_parsed", "updated_parsed"):
        t = bejegyzes.get(mezo)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def feed_letoltes(url):
    valasz = requests.get(url, headers=FEJLEC, timeout=20)
    valasz.raise_for_status()
    feed = feedparser.parse(valasz.content)
    if not feed.entries and feed.bozo:
        raise ValueError("a válasz nem RSS-csatorna")
    return feed


def feed_felderites(url):
    """Ha a megadott címek nem működnek, megkeresi a csatornát az oldal főoldalán
    (a <link rel="alternate" type="application/rss+xml"> címkékből)."""
    gyoker = "{0.scheme}://{0.netloc}/".format(urlparse(url))
    valasz = requests.get(gyoker, headers=FEJLEC, timeout=20)
    valasz.raise_for_status()
    for cimke in re.findall(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>",
                            valasz.text, re.I):
        m = re.search(r"href=[\"']([^\"']+)", cimke)
        if m:
            yield urljoin(gyoker, html.unescape(m.group(1)))


def feed_keresese(cimek):
    """Végigpróbálja a megadott címeket, majd az oldalon felfedezett csatornákat.
    Visszaadja: (feed, a sikeres cím, a megadott címek egyike volt-e)."""
    cimek = [cimek] if isinstance(cimek, str) else list(cimek)
    hibak = []
    for url in cimek:
        try:
            return feed_letoltes(url), url, True
        except Exception as e:
            hibak.append(f"{url}: {e}")
    try:
        for url in feed_felderites(cimek[0]):
            if url in cimek:
                continue
            try:
                return feed_letoltes(url), url, False
            except Exception as e:
                hibak.append(f"{url}: {e}")
    except Exception as e:
        hibak.append(f"főoldal: {e}")
    raise RuntimeError(" | ".join(hibak))


def hirek_letoltese(forrasok):
    hatar = datetime.now(timezone.utc) - timedelta(hours=MAX_ORA)
    cikkek = []
    for nev, cimek in forrasok.items():
        try:
            feed, hasznalt, megadott = feed_keresese(cimek)
        except Exception as e:
            print(f"  ! {nev}: nem sikerült letölteni ({e})", file=sys.stderr)
            continue
        if not megadott:
            print(f"  i {nev}: működő csatorna felfedezve: {hasznalt}")

        db = 0
        for b in feed.entries:
            ido = cikk_ideje(b)
            if ido and ido < hatar:
                continue
            cim = tisztit(b.get("title"), 220)
            link = b.get("link")
            if not cim or not link:
                continue
            lead = tisztit(b.get("summary"))
            if lead.lower().startswith(cim.lower()[:40]):
                lead = ""   # a lead csak a címet ismételné
            cikkek.append({
                "forras": nev,
                "cim": cim,
                "lead": lead,
                "url": link,
                "ido": ido or datetime.now(timezone.utc),
            })
            db += 1
            if db >= MAX_CIKK_FORRASONKENT:
                break
        print(f"  {nev}: {db} cikk")
    return cikkek


# ---------------------------------------------------------------------------
# Csoportosítás és rangsorolás
# ---------------------------------------------------------------------------

def szotovek(cim):
    """Ékezet nélküli, kisbetűs szavak első 5 betűje – így a ragozott alakok is egyeznek."""
    s = unicodedata.normalize("NFKD", cim.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {w[:5] for w in re.findall(r"[a-z0-9]+", s) if len(w) > 3}


def hasonlosag(a, b):
    if not a or not b:
        return 0.0
    kozos = len(a & b)
    return kozos / min(len(a), len(b)) if kozos >= 2 else 0.0


def csoportosit(cikkek):
    """Mohó csoportosítás: az azonos eseményről szóló cikkek egy csoportba kerülnek."""
    csoportok = []
    for c in sorted(cikkek, key=lambda x: x["ido"], reverse=True):
        c["_szavak"] = szotovek(c["cim"])
        for cs in csoportok:
            if hasonlosag(c["_szavak"], cs["szavak"]) >= HASONLOSAG:
                cs["cikkek"].append(c)
                cs["szavak"] |= c["_szavak"]
                break
        else:
            csoportok.append({"cikkek": [c], "szavak": set(c["_szavak"])})
    return csoportok


def kivalaszt(csoportok, darab):
    """Előre veszi a több forrásban szereplő híreket, azon belül a frissebbeket."""
    for cs in csoportok:
        cs["forrasszam"] = len({c["forras"] for c in cs["cikkek"]})
        cs["legujabb"] = max(c["ido"] for c in cs["cikkek"])
    rangsor = sorted(csoportok, key=lambda cs: (-cs["forrasszam"], -cs["legujabb"].timestamp()))

    kivalasztott, egyforrasos = [], {}
    for cs in rangsor:
        if cs["forrasszam"] == 1:
            forras = cs["cikkek"][0]["forras"]
            if egyforrasos.get(forras, 0) >= MAX_EGYFORRASOS_FORRASONKENT:
                continue
            egyforrasos[forras] = egyforrasos.get(forras, 0) + 1
        kivalasztott.append(cs)
        if len(kivalasztott) >= darab:
            break
    return kivalasztott


def hir_epitese(cs):
    # Címadó: a leghosszabb leadű cikk (ott van a legtöbb információ)
    cikkek = sorted(cs["cikkek"], key=lambda c: len(c["lead"]), reverse=True)
    fo = cikkek[0]
    forrasok, latott = [], set()
    for c in cikkek:
        if c["forras"] in latott:
            continue
        latott.add(c["forras"])
        forrasok.append({"nev": c["forras"], "cim": c["cim"], "url": c["url"]})
    return {"cim": fo["cim"], "lead": fo["lead"], "forrasok": forrasok}


def hirek_osszeallitasa(forrasok, darab):
    cikkek = hirek_letoltese(forrasok)
    print(f"  Összesen {len(cikkek)} cikk.")
    csoportok = csoportosit(cikkek)
    return [hir_epitese(cs) for cs in kivalaszt(csoportok, darab)]


# ---------------------------------------------------------------------------
# Fordítás (csak a nemzetközi hírekhez)
# ---------------------------------------------------------------------------

def fordit(hirek):
    """A hírek címét és leadjét magyarra fordítja (helyben módosít).
    A források listája (eredeti angol címek) érintetlen marad.
    Visszatérési érték: sikerült-e a fordítás."""
    if not hirek:
        return False
    if not API_KULCS:
        print("Nincs GEMINI_API_KEY: a nemzetközi hírek fordítás nélkül, angolul maradnak.")
        return False

    bemenet = [{"cim": h["cim"], "lead": h["lead"]} for h in hirek]
    prompt = FORDITAS_PROMPT.replace("__BEMENET__", json.dumps(bemenet, ensure_ascii=False))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELL}:generateContent"
    torzs = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }

    for kiserlet in range(1, 4):
        try:
            v = requests.post(
                url,
                headers={"x-goog-api-key": API_KULCS, "Content-Type": "application/json"},
                json=torzs,
                timeout=120,
            )
            if v.status_code != 200:
                raise RuntimeError(f"HTTP {v.status_code}: {v.text[:300]}")
            szoveg = v.json()["candidates"][0]["content"]["parts"][0]["text"]
            szoveg = re.sub(r"^```(?:json)?|```$", "", szoveg.strip()).strip()
            adat = json.loads(szoveg)
            if not isinstance(adat, list) or len(adat) != len(hirek):
                raise ValueError("a fordítás elemszáma nem egyezik a bemenetével")
            if not all(isinstance(f, dict) for f in adat):
                raise ValueError("a fordítás formátuma hibás")
            for h, f in zip(hirek, adat):
                cim = str(f.get("cim") or "").strip()
                lead = str(f.get("lead") or "").strip()
                if cim:
                    h["cim"] = cim
                if lead:
                    h["lead"] = lead
            print(f"Nemzetközi hírek lefordítva ({MODELL}).")
            return True
        except Exception as e:
            print(f"  ! Fordítási hiba ({kiserlet}. próba): {e}", file=sys.stderr)
            if kiserlet < 3:
                time.sleep(15 * kiserlet)
    print("A fordítás nem sikerült, a nemzetközi hírek angolul maradnak.", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Mentés
# ---------------------------------------------------------------------------

def mentes(adat):
    archiv = KIMENET / "archiv"
    archiv.mkdir(parents=True, exist_ok=True)

    json_szoveg = json.dumps(adat, ensure_ascii=False, indent=2)
    (KIMENET / "hirek.json").write_text(json_szoveg, encoding="utf-8")
    (archiv / f"{adat['datum']}.json").write_text(json_szoveg, encoding="utf-8")

    datumok = sorted((p.stem for p in archiv.glob("????-??-??.json")), reverse=True)
    (archiv / "index.json").write_text(json.dumps(datumok, indent=2), encoding="utf-8")
    print(f"Mentve: docs/hirek.json és docs/archiv/{adat['datum']}.json")


# ---------------------------------------------------------------------------
# Fő program
# ---------------------------------------------------------------------------

def main():
    print("Hazai hírek:")
    hazai = hirek_osszeallitasa(HAZAI_FORRASOK, HAZAI_DB)
    print("Nemzetközi hírek:")
    nemzetkozi = hirek_osszeallitasa(NEMZETKOZI_FORRASOK, NEMZETKOZI_DB)

    if not hazai and not nemzetkozi:
        raise SystemExit("Egyetlen hírt sem sikerült letölteni, nem írom felül a korábbi listát.")

    forditva = fordit(nemzetkozi)

    most = datetime.now(IDOZONA)
    adat = {
        "datum": most.strftime("%Y-%m-%d"),
        "generalva": most.isoformat(timespec="minutes"),
        "hazai": hazai,
        "nemzetkozi": nemzetkozi,
    }
    if forditva:
        adat["fordites"] = MODELL
    mentes(adat)


if __name__ == "__main__":
    main()
