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

## Bezpečné nastavenie

Dodávateľská URL obsahuje súkromný hash a nesmie byť v repozitári. V GitHub nastaveniach vytvorte Actions secret `SOURCE_FEED_URL` s celou adresou zdrojového XML.

Potom povoľte GitHub Pages cez **Settings → Pages → Source: GitHub Actions** a spustite workflow **Build AMDPRO feed** ručne. Výsledok bude dostupný ako `feed-pl.xml` na Pages adrese repozitára.

## Stav prekladov

Aktuálny výstup zachováva pôvodný poľský názov a kategóriu. SK/CZ/HU výstupy sa nesmú zapnúť, kým nebude doplnená a skontrolovaná profesionálna prekladová pamäť. Shoptet zatiaľ neprepínajte na túto URL.
