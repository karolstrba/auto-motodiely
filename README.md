# AMDPRO product feed

Bezplatný generátor dynamického XML feedu pre AMDPRO.

## Čo robí

- pri každom spustení načíta aktuálny dodávateľský feed,
- vyberie najviac 44 000 produktov s kladným skladom,
- prioritne zachová pneumatiky, duše, oblečenie, prilby, obuv a chrániče,
- ostatný sortiment zoradí podľa skladu a kvality údajov,
- po opätovnom naskladnení produkt znovu automaticky vyhodnotí,
- publikuje platné XML cez GitHub Pages,
- spúšťa sa automaticky každých 6 hodín.

## Allegro Automotodiely – bezpečný náhľad

Pri každom spustení vznikne aj privátny Actions artefakt `allegro-preview`.
Je oddelený od verejného Shoptet
feedu a obsahuje všetky produkty vrátane nulového skladu, aby sa dali ponuky
neskôr automaticky pozastaviť a po naskladnení obnoviť.

- cena sa prepočíta z PLN na EUR aktuálnym kurzom ECB a zvýši o 10 %,
- sklad sa kopíruje zo zdrojového XML,
- nové produkty sa označia `ready` iba pri platnom EAN, cene a obrázku,
- chýbajúce údaje sú uvedené v stĺpci `blocking_reason`,
- súbor sám nič nemení na Allegre; živá API synchronizácia zostáva vypnutá.
- náhľad sa nepublikuje cez GitHub Pages a po 7 dňoch sa automaticky odstráni.

Týmto sa nemení cena ani štruktúra existujúceho `feed-pl.xml` pre Shoptet.

## Bezpečné nastavenie

Dodávateľská URL obsahuje súkromný hash a nesmie byť v repozitári. V GitHub nastaveniach vytvorte Actions secret `SOURCE_FEED_URL` s celou adresou zdrojového XML.

Potom povoľte GitHub Pages cez **Settings → Pages → Source: GitHub Actions** a spustite workflow **Build AMDPRO feed** ručne. Výsledok bude dostupný ako `feed-pl.xml` na Pages adrese repozitára.

## Stav prekladov

Aktuálny výstup zachováva pôvodný poľský názov a kategóriu. SK/CZ/HU výstupy sa nesmú zapnúť, kým nebude doplnená a skontrolovaná profesionálna prekladová pamäť. Shoptet zatiaľ neprepínajte na túto URL.
