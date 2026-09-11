#!/usr/bin/env python3
"""Complete hourly Moto-Maniak feed for AMDPRO/Shoptet."""
from __future__ import annotations

import csv, html, json, os, re, tempfile, time, unicodedata, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

STOCK_URL = "https://www.moto-maniak.eu/xml/stanymag12.csv"
CATALOG_URL = "https://www.moto-maniak.eu/export/strba090926.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
PREFIX, ROOT = "MM-", "ATV/UTV diely"
A = ROOT

# Only category paths that already exist in AMDPRO's supplied category export.
RULES = [
 (r"ODZIEZ.*REKAWIC|REKAWIC", "Oblečenie / Motokrosové oblečenie / Rukavice"),
 (r"ODZIEZ.*KURTK|KURTK", "Oblečenie / Motokrosové oblečenie / Bundy"),
 (r"ODZIEZ.*SPODN|SPODNIE", "Oblečenie / Motokrosové oblečenie / Nohavice"),
 (r"ODZIEZ.*KOSZUL|JERSEY", "Oblečenie / Motokrosové oblečenie / Dresy"),
 (r"GOGLE|GOGGLES", "Výstroj a ochrana / Prilby a okuliare / Motokrosové okuliare"),
 (r"KASK|HELMET", "Výstroj a ochrana / Prilby a okuliare / Prilby"),
 (r"BUTY|OBUWIE", "Výstroj a ochrana / Čižmy"),
 (r"OCHRANIACZ.*KOLAN", "Výstroj a ochrana / Chrániče / Chrániče kolien"),
 (r"OCHRANIACZ.*LOK", "Výstroj a ochrana / Chrániče / Chrániče lakťov"),
 (r"OCHRANIACZ", "Výstroj a ochrana / Chrániče"),
 (r"NARZEDZI|KLUCZ", "Príslušenstvo a depo / Depo a dielňa / Náradie"),
 (r"WYCIAGARK.*(LIN|AKCES)|LINY I AKCESORIA", "Príslušenstvo a depo / Doplnky na ATV/UTV / Príslušenstvo k navijakom"),
 (r"WYCIAGARK", "Príslušenstvo a depo / Doplnky na ATV/UTV / Navijaky"),
 (r"KUFR|TORB", "Príslušenstvo a depo / Doplnky na ATV/UTV / Kufre a boxy"),
 (r"LUSTERK", "Príslušenstvo a depo / Doplnky na ATV/UTV / Zrkadlá"),
 (r"POKROWIEC|PLANDEK", "Príslušenstvo a depo / Doplnky na ATV/UTV / Krycie plachty"),
 (r"PLUG|LEMIESZ", "Príslušenstvo a depo / Doplnky na ATV/UTV / Radlice a príslušenstvo"),
 (r"HAK|HOLOWNIC", "Príslušenstvo a depo / Doplnky na ATV/UTV / Ťažné zariadenia"),
 (r"KANISTER|AKCESORIA ROZNE|BRELOCZ|WYPRZEDA", "Príslušenstvo a depo / Doplnky na ATV/UTV"),
 (r"KLOCKI HAMULC|BRAKE PAD", f"{A} / Brzdy / Brzdové platničky"),
 (r"TARCZ.*HAMULC|BRAKE DISC", f"{A} / Brzdy / Brzdové kotúče"),
 (r"ZACISK.*HAMULC", f"{A} / Brzdy / Brzdové strmene"),
 (r"PRZEWOD.*HAMULC|BRAKE HOSE", f"{A} / Brzdy / Brzdové hadice"),
 (r"POMP.*HAMULC|CYLINDER HAMULC", f"{A} / Brzdy / Brzdové valce"),
 (r"NAPRAWCZ.*HAMULC", f"{A} / Brzdy / Opravné sady bŕzd"),
 (r"ROZRUSZNIK", f"{A} / Elektrika a zapaľovanie / Štartéry"),
 (r"ALTERNATOR|STATOR|UZWOJEN", f"{A} / Elektrika a zapaľovanie / Alternátory a statory"),
 (r"REGULATOR.*NAP", f"{A} / Elektrika a zapaľovanie / Regulátory napätia"),
 (r"CEWK.*ZAP", f"{A} / Elektrika a zapaľovanie / Zapaľovacie cievky"),
 (r"SWIEC", f"{A} / Elektrika a zapaľovanie / Zapaľovacie sviečky"),
 (r"CDI|MODUL.*ZAPLON", f"{A} / Elektrika a zapaľovanie / CDI a riadiace jednotky"),
 (r"PRZEKAZ", f"{A} / Elektrika a zapaľovanie / Relé"),
 (r"CZUJNIK", f"{A} / Elektrika a zapaľovanie / Snímače"),
 (r"PRZELACZN|STACYJK", f"{A} / Elektrika a zapaľovanie / Ovládače a vypínače"),
 (r"AKUMULATOR|BATERI", f"{A} / Elektrika a zapaľovanie / Batérie"),
 (r"LAMP|OSWIETL|KIERUNKOW", f"{A} / Elektrika a zapaľovanie / Osvetlenie"),
 (r"CHLODNIC", f"{A} / Chladenie / Chladiče"),
 (r"WENTYLATOR", f"{A} / Chladenie / Ventilátory chladiča"),
 (r"POMP.*WOD", f"{A} / Chladenie / Vodné pumpy"),
 (r"TERMOSTAT", f"{A} / Chladenie / Termostaty"),
 (r"(PRZEWOD|WAZ).*CHLO", f"{A} / Chladenie / Hadice chladiča"),
 (r"KOREK.*CHLO", f"{A} / Chladenie / Viečka chladiča"),
 (r"POMP.*PALIW", f"{A} / Palivová sústava / Palivové čerpadlá"),
 (r"GAZNIK", f"{A} / Palivová sústava / Karburátory"),
 (r"WTRYSK", f"{A} / Palivová sústava / Vstrekovanie"),
 (r"FILTR.*PALIW", f"{A} / Palivová sústava / Palivové filtre"),
 (r"ZAWOR.*PALIW|PRZEWOD.*PALIW", f"{A} / Palivová sústava / Palivové ventily a hadice"),
 (r"ZBIORNIK.*PALIW", f"{A} / Palivová sústava / Palivové nádrže"),
 (r"PASEK|PASKI NAPED", f"{A} / Prevodovka a spojka / Remene variátora"),
 (r"WARIATOR", f"{A} / Prevodovka a spojka / Variátory"),
 (r"SPRZEGL", f"{A} / Prevodovka a spojka / Spojky"),
 (r"SKRZYN.*BIEG|PRZEKLADN", f"{A} / Prevodovka a spojka / Prevodovky"),
 (r"DZWIGN.*ZMIAN|WYBIERAK", f"{A} / Prevodovka a spojka / Radiace mechanizmy"),
 (r"POLOS", f"{A} / Pohon a prevod / Poloosi"),
 (r"PRZEGUB", f"{A} / Pohon a prevod / Homokinetické kĺby"),
 (r"WAL.*NAPED|KARDAN", f"{A} / Pohon a prevod / Kardany"),
 (r"DYFERENC", f"{A} / Pohon a prevod / Diferenciály"),
 (r"LANCUCH", f"{A} / Pohon a prevod / Reťaze"),
 (r"ZEBAT|ROZET", f"{A} / Pohon a prevod / Rozety a reťazové kolieska"),
 (r"MANSZET|GUM.*PRZEG|OSLON.*PRZEG", f"{A} / Pohon a prevod / Manžety poloosí"),
 (r"OPON", f"{A} / Kolesá a pneumatiky / ATV/UTV pneumatiky"),
 (r"FELG", f"{A} / Kolesá a pneumatiky / Disky"),
 (r"DETK", f"{A} / Kolesá a pneumatiky / Duše"),
 (r"LOZYSK.*KOL", f"{A} / Kolesá a pneumatiky / Ložiská kolies"),
 (r"PIAST|HUBY", f"{A} / Kolesá a pneumatiky / Náboje kolies"),
 (r"NAKRETK.*KOL|KAPSLE NAK", f"{A} / Kolesá a pneumatiky / Matice a skrutky kolies"),
 (r"SWORZEN|KONCOWK.*DRAZ", f"{A} / Riadenie a podvozok / Guľové čapy"),
 (r"DRAZK.*KIER", f"{A} / Riadenie a podvozok / Tyče riadenia"),
 (r"WAHACZ", f"{A} / Riadenie a podvozok / A-ramená"),
 (r"AMORTYZATOR", f"{A} / Riadenie a podvozok / Tlmiče"),
 (r"SPREZYN", f"{A} / Riadenie a podvozok / Pružiny"),
 (r"KIEROWNIC|MANETK|MAGLOWNIC", f"{A} / Riadenie a podvozok / Riadidlá a rukoväte"),
 (r"ZESTAW.*WAHACZ|TULEJ", f"{A} / Riadenie a podvozok / Puzdrá a opravné sady podvozka"),
 (r"TLOK|PIERSCIEN.*TLOK", f"{A} / Motor / Piesty a piestne sady"),
 (r"CYLINDR|GLOWIC", f"{A} / Motor / Valce a hlavy"),
 (r"WAL KORB|KORBOWOD", f"{A} / Motor / Ojnice a kľukové hriadele"),
 (r"ZAWOR|ROZRZAD", f"{A} / Motor / Ventily a rozvody"),
 (r"LOZYSK.*SILN", f"{A} / Motor / Ložiská motora"),
 (r"USZCZELK.*SILN|USZCZELNIACZ.*SILN|SIMERING", f"{A} / Motor / Tesnenia a guferá motora"),
 (r"POKRYW.*SILN|OSLON.*SILN", f"{A} / Motor / Kryty motora"),
 (r"KOLANKO.*WYDECH|KOLEKTOR.*WYDECH", f"{A} / Výfukový systém / Výfukové zvody"),
 (r"USZCZELK.*WYDECH", f"{A} / Výfukový systém / Tesnenia výfuku"),
 (r"WYDECH|TLUMIK", f"{A} / Výfukový systém / Výfuky"),
 (r"PLAST|OWIEWK", f"{A} / Karoséria a ochranné prvky / Plasty a kapotáže"),
 (r"BLOTNIK", f"{A} / Karoséria a ochranné prvky / Blatníky"),
 (r"SIEDZEN|POKROWIEC.*SIED", f"{A} / Karoséria a ochranné prvky / Sedadlá a poťahy"),
 (r"ZDERZAK", f"{A} / Karoséria a ochranné prvky / Nárazníky"),
 (r"OSLON", f"{A} / Karoséria a ochranné prvky / Kryty podvozka"),
 (r"HANDGUARD", f"{A} / Karoséria a ochranné prvky / Chrániče rúk"),
 (r"PODNOZ", f"{A} / Karoséria a ochranné prvky / Stupačky"),
 (r"LOZYSK.*KIER", f"{A} / Ložiská a tesnenia / Ložiská riadenia"),
 (r"LOZYSK.*WAH|LOZYSK.*RAM", f"{A} / Ložiská a tesnenia / Ložiská ramien"),
 (r"LOZYSK.*OSI|LOZYSK.*WAL", f"{A} / Ložiská a tesnenia / Ložiská náprav"),
 (r"USZCZELNIACZ|SIMERING", f"{A} / Ložiská a tesnenia / Guferá"),
 (r"USZCZELK", f"{A} / Ložiská a tesnenia / Tesnenia"),
 (r"FILTR.*OLEJ", "Motodiely / Motor / Filtre / Olejové filtre"),
 (r"FILTR.*POWIETR", "Motodiely / Motor / Filtre / Vzduchové filtre"),
]

# Product terminology used in the supplier catalogue. Longer expressions are
# replaced first; model names, dimensions, years and OEM numbers stay intact.
PHRASES = [
 (r"zestaw homologacyjny do pojazdu utv ssv", "homologizačná sada pre vozidlo UTV/SSV"),
 (r"do łatania dziur w oponie", "na opravu defektov pneumatiky"),
 (r"najazdy aluminiowe składane blacha ryflowana komplet 2\s*szt", "skladacie hliníkové nájazdové rampy s protišmykovým povrchom, sada 2 ks"),
 (r"do (?:klejenia|naprawy) dziur w oponie", "na opravu defektov pneumatiky"),
 (r"i wiele innych atv/utv przeprawowych z rozstawem", "a ďalšie terénne ATV/UTV s roztečou"),
 (r"zestaw szybkiego otwierania", "sada rýchleho otvárania"),
 (r"pilot bezprzewodowy radiowy", "bezdrôtový diaľkový ovládač"),
 (r"bez sterownika", "bez riadiacej jednotky"),
 (r"zestaw homologacyjny", "homologizačná sada"),
 (r"i wiele innych", "a ďalšie"),
 (r"sznury butylowe", "butylové opravné knôty"),
 (r"do dziur w oponie", "na opravu defektov pneumatiky"),
 (r"olej do tylnego mostu z hamulcem mokrym", "olej do zadného diferenciálu s mokrou brzdou"),
 (r"uszczelka pod pokrywę zaworową", "tesnenie veka ventilov"),
 (r"uszczelniacze zaworowe", "guferá ventilov"),
 (r"uszczelniacz zaworowy", "gufero ventilu"),
 (r"łożysko dolne kolumny kierowniczej", "dolné ložisko stĺpika riadenia"),
 (r"mocowanie dolne kufra przedniego", "dolný držiak predného kufra"),
 (r"panel drzwiowy", "dverový panel"),
 (r"panel drzwi", "dverový panel"),
 (r"tworzywo sztuczne", "plast"),
 (r"podgrzewany kciuk", "vyhrievanie palca"),
 (r"sterownik do podgrzewanych manetek", "ovládač vyhrievaných rukovätí"),
 (r"cylinderek hamulcowy", "brzdový valec"),
 (r"punktowe podświetlenie pojazdu", "bodové podsvietenie vozidla"),
 (r"sterowane smartfonem", "ovládané smartfónom"),
 (r"z czujnikami", "so snímačmi"),
 (r"bez czujnika", "bez snímača"),
 (r"z mocowaniami", "s držiakmi"),
 (r"łożyska kół", "ložiská kolies"),
 (r"zestaw naprawczy wahacza", "opravná sada ramena"),
 (r"końcówki drążków kierowniczych", "čapy riadiacich tyčí"),
 (r"pierścienie tłokowe", "piestne krúžky"),
 (r"wałek rozrządu", "vačkový hriadeľ"),
 (r"łańcuch rozrządu", "rozvodová reťaz"),
 (r"ślizg łańcucha", "vodidlo reťaze"),
 (r"łącznik stabilizatora", "tyčka stabilizátora"),
 (r"guma stabilizatora", "puzdro stabilizátora"),
 (r"sprzęgło wtórne", "sekundárna spojka"),
 (r"sprzęgło pierwotne", "primárna spojka"),
 (r"talerz sprzęgła", "tanier spojky"),
 (r"rolki wariatora", "valčeky variátora"),
 (r"cewka magneta", "stator zapaľovania"),
 (r"korek wlewu paliwa", "uzáver palivovej nádrže"),
 (r"linka gazu", "plynové lanko"),
 (r"dźwignia zmiany biegów", "radiaca páka"),
 (r"czujnik prędkości", "snímač rýchlosti"),
 (r"czujnik położenia przepustnicy", "snímač polohy škrtiacej klapky"),
 (r"sonda lambda", "lambda sonda"),
 (r"moduł zapłonowy", "zapaľovací modul"),
 (r"przewód wysokiego napięcia", "vysokonapäťový kábel"),
 (r"osłona dłoni", "chránič rúk"),
 (r"szyba przednia", "čelné sklo"),
 (r"lampa tylna", "zadné svetlo"),
 (r"lampa przednia", "predné svetlo"),
 (r"żarówka led", "LED žiarovka"),
 (r"zestaw montażowy", "montážna sada"),
 (r"zestaw uszczelek silnika top[- ]end", "sada tesnení hornej časti motora"),
 (r"komplet uszczelek na silnik", "kompletná sada tesnení motora"),
 (r"zestaw uszczelek silnika", "sada tesnení motora"),
 (r"uszczelka pod głowicę", "tesnenie pod hlavu"),
 (r"sterowanie do wyciągarki", "ovládanie navijaka"),
 (r"przełącznik kierunkowskazów i klaksonu", "prepínač smeroviek a klaksónu"),
 (r"nakrętka chromowana do alufelg", "chrómovaná matica na hliníkové disky"),
 (r"nakrętka czarna do alufelg", "čierna matica na hliníkové disky"),
 (r"nakrętka przelotowa do felg aluminiowych", "priechodná matica na hliníkové disky"),
 (r"nakrętka przelotowa do alufelg", "priechodná matica na hliníkové disky"),
 (r"hak holowniczy na tył", "zadné ťažné zariadenie"),
 (r"uchwyt lamp dachowych", "držiak strešných svetiel"),
 (r"uchwyt lusterka", "držiak zrkadla"),
 (r"uchwyt na szpadel", "držiak na rýľ"),
 (r"torby na drzwi", "tašky na dvere"),
 (r"torba na dach", "strešná taška"),
 (r"poszerzenia nadkoli", "rozšírenia blatníkov"),
 (r"panewki wału korbowego", "ložiskové panvy kľukového hriadeľa"),
 (r"łożysko piasty tylnej", "ložisko zadného náboja"),
 (r"uszczelniacz dyferencjału przedniego", "gufero predného diferenciálu"),
 (r"uszczelniacz dyferencjału tylnego", "gufero zadného diferenciálu"),
 (r"czujnik luzu oraz biegu wstecznego", "snímač neutrálu a spiatočky"),
 (r"adapter czujnika temperatury", "adaptér snímača teploty"),
 (r"przełącznik z przewodami", "prepínač s kabelážou"),
 (r"zderzak gumowy do wyciągarki", "gumový doraz navijaka"),
 (r"zderzak do wyciągarki", "doraz navijaka"),
 (r"pokrowiec na quada", "ochranná plachta na ATV"),
 (r"gumy i uszczelniacze", "gumové diely a guferá"),
 (r"krzyżak wału napędowego przedniego lub tylnego", "kríž predného alebo zadného hnacieho hriadeľa"),
 (r"na przód lub tył", "na prednú alebo zadnú nápravu"),
 (r"lewy lub prawy", "ľavý alebo pravý"),
 (r"lewa lub prawa", "ľavá alebo pravá"),
 (r"przedni lub tylny", "predný alebo zadný"),
 (r"przednia lub tylna", "predná alebo zadná"),
 (r"z uchwytami na kierownicę", "s držiakmi na riadidlá"),
 (r"na klucz", "na kľúč"),
 (r"zamiennik oryginału", "náhrada originálneho dielu"),
 (r"zamiennik oem", "náhrada OEM dielu"),
 (r"rękawice tekstylne", "textilné rukavice"),
 (r"wtyczka gniazdo andersona", "Anderson zástrčka a zásuvka"),
 (r"w kolorze", "vo farbe"),
 (r"lewarek zmiany biegów", "radiaca páka"),
 (r"lewarka zmiany", "radiacej páky"),
 (r"przyrząd do wymiany paska napędowego", "náradie na výmenu hnacieho remeňa"),
 (r"końcówka wewnętrzna drążka kierowniczego", "vnútorný čap riadiacej tyče"),
 (r"końcówka zewnętrzna drążka kierowniczego", "vonkajší čap riadiacej tyče"),
 (r"końcówka drążka kierowniczego", "čap riadiacej tyče"),
 (r"sworzeń kulisty zwrotnicy", "guľový čap náboja kolesa"),
 (r"sworzeń kulisty wahacza", "guľový čap ramena"),
 (r"sworzeń wahacza", "čap ramena"),
 (r"klocki hamulcowe", "brzdové platničky"),
 (r"szczęki hamulcowe", "brzdové čeľuste"),
 (r"tarcza hamulcowa", "brzdový kotúč"),
 (r"zacisk hamulcowy", "brzdový strmeň"),
 (r"pompa hamulcowa", "brzdový valec"),
 (r"przewód hamulcowy", "brzdová hadica"),
 (r"zestaw naprawczy", "opravná sada"),
 (r"zestaw uszczelek", "sada tesnení"),
 (r"komplet uszczelek", "kompletná sada tesnení"),
 (r"filtr powietrza", "vzduchový filter"),
 (r"filtr oleju", "olejový filter"),
 (r"filtr paliwa", "palivový filter"),
 (r"pompa paliwa", "palivové čerpadlo"),
 (r"pompa wody", "vodná pumpa"),
 (r"pompa oleju", "olejové čerpadlo"),
 (r"wtryskiwacz paliwa", "vstrekovač paliva"),
 (r"wtrysk paliwa", "vstrekovanie paliva"),
 (r"króciec ssący", "sacie hrdlo"),
 (r"przełącznik zespolony", "združený prepínač"),
 (r"przekaźnik rozrusznika", "štartovacie relé"),
 (r"uzwojenie alternatora", "vinutie alternátora"),
 (r"cewka zapłonowa", "zapaľovacia cievka"),
 (r"regulator napięcia", "regulátor napätia"),
 (r"czujnik temperatury", "snímač teploty"),
 (r"czujnik położenia", "snímač polohy"),
 (r"wał korbowy", "kľukový hriadeľ"),
 (r"wał napędowy", "hnací hriadeľ"),
 (r"krzyżak wału napędowego", "kríž hnacieho hriadeľa"),
 (r"jarzmo wału napędowego", "strmeň hnacieho hriadeľa"),
 (r"pasek napędowy", "hnací remeň"),
 (r"łańcuch rozrządu", "rozvodová reťaz"),
 (r"sprzęgło rozrusznika", "štartovacia spojka"),
 (r"guma przegubu", "manžeta kĺbu"),
 (r"manszeta przegubu", "manžeta kĺbu"),
 (r"łożysko piasty koła", "ložisko kolesa"),
 (r"łożysko jednokierunkowe", "jednosmerné ložisko"),
 (r"łożysko igiełkowe", "ihlové ložisko"),
 (r"uszczelniacz dyferencjału", "gufero diferenciálu"),
 (r"uszczelka pokrywy", "tesnenie krytu"),
 (r"uszczelka głowicy", "tesnenie hlavy"),
 (r"chłodnica wody", "chladič vody"),
 (r"wentylator chłodnicy", "ventilátor chladiča"),
 (r"korek chłodnicy", "viečko chladiča"),
 (r"osłony amortyzatorów", "chrániče tlmičov"),
 (r"drążek kierowniczy", "tyč riadenia"),
 (r"maglownica kierownicza", "prevodka riadenia"),
 (r"felga aluminiowa", "hliníkový disk"),
 (r"oś tylna", "zadná náprava"),
 (r"półoś przednia", "predná poloos"),
 (r"półoś tylna", "zadná poloos"),
 (r"tylny kufer", "zadný kufor"),
 (r"zestaw naklejek", "sada nálepiek"),
 (r"włącznik zapłonu", "spínač zapaľovania"),
 (r"włącznik świateł", "spínač svetiel"),
 (r"hak z przetyczką", "hák s poistným kolíkom"),
 (r"listwa led", "LED svetelná rampa"),
 (r"panel led", "LED svetelný panel"),
 (r"światło wsteczne", "cúvacie svetlo"),
 (r"kierunkowskaz", "smerovka"),
 (r"na tył", "na zadnú nápravu"),
]
WORDS = {
 "przedni":"predný", "przednia":"predná", "przednie":"predné", "przedniego":"predného", "przednich":"predných", "przedniej":"prednej", "przedne":"predné",
 "tylny":"zadný", "tylna":"zadná", "tylne":"zadné", "tylnego":"zadného", "tylnej":"zadnej",
 "lewy":"ľavý", "lewa":"ľavá", "lewe":"ľavé", "prawy":"pravý", "prawa":"pravá", "prawe":"pravé",
 "górny":"horný", "górna":"horná", "dolny":"dolný", "dolna":"dolná",
 "wewnętrzny":"vnútorný", "wewnętrzna":"vnútorná", "zewnętrzny":"vonkajší", "zewnętrzna":"vonkajšia",
 "kompletny":"kompletný", "kompletna":"kompletná", "komplet":"komplet", "zestaw":"sada",
 "osłona":"kryt", "osłony":"kryty", "pokrywa":"kryt", "mocowanie":"držiak",
 "łożysko":"ložisko", "łożyska":"ložiská", "uszczelka":"tesnenie", "uszczelniacz":"gufero",
 "tuleja":"puzdro", "tuleje":"puzdrá", "wahacz":"rameno", "amortyzator":"tlmič", "sprężyna":"pružina",
 "półoś":"poloos", "przegub":"kĺb", "dyferencjału":"diferenciálu", "dyferencjał":"diferenciál",
 "wał":"hriadeľ", "wału":"hriadeľa", "napędowy":"hnací", "napędowego":"hnacieho",
 "rozrusznik":"štartér", "rozrusznika":"štartéra", "stacyjka":"spínacia skrinka",
 "przełącznik":"prepínač", "włącznik":"spínač", "czujnik":"snímač", "pompa":"čerpadlo",
 "chłodnica":"chladič", "wentylator":"ventilátor", "wariator":"variátor", "wariatora":"variátora",
 "sprzęgło":"spojka", "sprzęgła":"spojky", "gaźnik":"karburátor", "gaźnika":"karburátora",
 "filtr":"filter", "paliwa":"paliva", "powietrza":"vzduchu", "oleju":"oleja", "silnika":"motora",
 "tłok":"piest", "tłoka":"piesta", "cylinder":"valec", "głowica":"hlava", "zawór":"ventil",
 "łańcuch":"reťaz", "zębatka":"reťazové koliesko", "felga":"disk", "opona":"pneumatika",
 "kierownicy":"riadidiel", "kierowniczy":"riadenia", "drążek":"tyč", "końcówka":"čap",
 "kufer":"kufor", "lusterko":"zrkadlo", "kanister":"kanister", "aluminiowa":"hliníkový",
 "czerwony":"červený", "czerwona":"červená", "czarny":"čierny", "czarna":"čierna",
 "niebieski":"modrý", "niebieska":"modrá", "zielony":"zelený", "biały":"biely", "biała":"biela",
 "uniwersalny":"univerzálny", "uniwersalna":"univerzálna", "oryginalny":"originálny", "oryginalna":"originálna",
 "zewnetrzny":"vonkajší", "zewnetrzna":"vonkajšia", "zewnetrznego":"vonkajšieho", "zewnętrznego":"vonkajšieho", "wewnetrzny":"vnútorný", "wewnetrzna":"vnútorná",
 "kolor":"farba", "kolorze":"farbe", "otwory":"otvory", "spinki":"spony", "wymiany":"výmenu", "paska":"remeňa",
 "rękawice":"rukavice", "tekstylne":"textilné", "rozmiar":"veľkosť", "rozm":"veľkosť", "letnie":"letné", "ocieplane":"zateplené",
 "czarne":"čierne", "czerwone":"červené", "niebieskie":"modré", "zielonym":"zelenej", "brazowy":"hnedá", "turkusowy":"tyrkysová", "szary":"sivá",
 "wodoszczelny":"vodotesný", "wodoszczelne":"vodotesné", "aluminiowy":"hliníkový", "stalowa":"oceľové", "stalowe":"oceľové",
 "piasty":"náboja", "sztuki":"kusy", "sztuka":"kus", "kominiarka":"kukla", "maska":"maska", "standard":"štandardná",
 "wyciagarki":"navijaka", "wyciągarki":"navijaka", "lampy":"svetlá", "obudowy":"kryty", "gniazdo":"zásuvka", "wtyczka":"zástrčka",
 "dwukolorowa":"dvojfarebná", "wspornik":"držiak", "zatyczka":"krytka", "ulepszona":"vylepšená", "wersja":"verzia",
 "manszeta":"manžeta", "lusterka":"zrkadlá", "pompy":"čerpadlá", "wsteczne":"cúvacie", "rozstaw":"rozteč",
 "dystanse":"rozširovacie podložky", "listwa":"rampa", "nowy":"nový", "szpilek":"štiftov", "maglownica":"prevodka riadenia",
 "zmiany":"radenia", "uniwersalne":"univerzálne", "wtryskiwacz":"vstrekovač", "piasta":"náboj", "pokrowiec":"poťah",
 "breloczek":"prívesok", "piankowy":"penový", "niezatapialny":"nepotopiteľný", "wydechu":"výfuku", "strona":"strana",
 "lampa":"svetlo", "mocowania":"držiaka", "hamulca":"brzdy", "aktuator":"aktuátor", "manetki":"rukoväte",
 "wzmacniany":"zosilnený", "modeli":"modelov", "gwint":"závit", "uszczelniacze":"guferá", "kierownice":"riadidlá",
 "dolnego":"dolného", "siedzenia":"sedadla", "talerz":"tanier", "felg":"diskov", "lina":"lano", "osadzenie":"uloženie",
 "napinacz":"napínač", "szyba":"čelné sklo", "poduszka":"silentblok", "prowadnica":"vodidlo", "kolumny":"stĺpika",
 "silnik":"motor", "manetka":"rukoväť", "zwrotnica":"otočný čap", "inne":"ostatné",
 "quadów":"ATV/UTV", "quada":"ATV/UTV", "części":"diel", "część":"diel", "naprawczy":"opravný",
 "do":"pre", "na":"na", "pod":"pod", "bez":"bez", "prawa":"pravá", "szt":"ks",
 "lub":"alebo", "oraz":"a", "zamiennik":"náhrada", "odpowiednik":"ekvivalent", "pasuje":"vhodné", "pasujący":"vhodný",
 "chromowana":"chrómovaná", "chromowany":"chrómovaný", "srebrny":"strieborný", "srebrna":"strieborná", "srebrne":"strieborné",
 "uchwyt":"držiak", "uchwyty":"držiaky", "uchwytami":"držiakmi", "obudowa":"kryt", "maskownica":"kryt",
 "nakrętka":"matica", "nakrętki":"matice", "aluminiowych":"hliníkové", "alufelg":"hliníkové disky", "klucz":"kľúč",
 "panewki":"ložiskové panvy", "syntetyczna":"syntetická", "neoprenowa":"neoprénová", "gumowe":"gumové",
 "kpl":"komplet", "przewody":"káble", "przewodami":"káblami", "chwilowy":"momentový", "dachowych":"strešných",
 "drzwi":"dvere", "torba":"taška", "torby":"tašky", "szpadel":"rýľ", "nawigacji":"navigácie",
 "akcesoria":"príslušenstvo", "dodatkowe":"doplnkové", "dodatkwe":"doplnkové", "dedykowany":"určený", "dedykowana":"určená",
 "wzmocniony":"zosilnený", "fabrycznie":"z výroby", "składany":"skladací", "składane":"skladacie", "łożyskowy":"ložiskový",
 "przelotowa":"priechodná", "poszerzenia":"rozšírenia", "nadkoli":"blatníkov", "mocowaniem":"držiakom",
 "gazu":"plynu", "przepustnicy":"škrtiacej klapky", "zacisku":"strmeňa", "hamulcowego":"brzdového",
 "wysokiego":"vysokého", "ciśnienia":"tlaku", "mokrego":"mokrej", "mokre":"mokré", "biegu":"rýchlostného stupňa",
 "luzu":"neutrálu", "przeznaczony":"určený", "przeznaczona":"určená", "zastosowanie":"kompatibilita",
 "przód":"predná časť", "tył":"zadná časť", "koła":"kolesa", "kół":"kolies", "otworów":"otvorov",
 "rozrządu":"rozvodov", "wahacza":"ramena", "górnego":"horného", "dolnego":"dolného", "sworzeń":"čap",
 "łańcucha":"reťaze", "ślizg":"vodidlo", "ślizgi":"vodidlá", "zrywające":"poistné", "wtórne":"sekundárne",
 "kufra":"kufra", "stabilizatora":"stabilizátora", "wody":"vody", "biegów":"radenia", "pojemność":"objem",
 "dłoni":"rúk", "mimośród":"excenter", "cały":"celý", "drążków":"tyčí", "pół":"polovica",
 "pierścienie":"krúžky", "tłokowe":"piestne", "szczęki":"čeľuste", "licznik":"prístrojový panel",
 "szpilka":"štift", "wałek":"hriadeľ", "dużo":"veľký", "błotników":"blatníkov", "wentylatora":"ventilátora",
 "kierownica":"riadidlá", "stożkowa":"kužeľová", "pojazdów":"vozidiel", "kierowniczych":"riadiacich",
 "zwiększona":"zvýšená", "firmy":"značky", "zestawem":"sadou", "montażowym":"montážnym", "pokrywy":"krytu",
 "położenia":"polohy", "elektroniczny":"elektronický", "napięcia":"napätia", "łańcuszka":"retiazky",
 "światłem":"svetlom", "zębate":"ozubené", "kierownicę":"riadidlá", "kierowniczej":"riadenia",
 "poprzeczka":"priečka", "tłoczek":"piestik", "moduł":"modul", "tłokowy":"piestový", "prędkości":"rýchlosti",
 "napedowy":"hnací", "gazowy":"plynový", "łańcuszek":"retiazka", "sprężyny":"pružiny", "króciec":"hrdlo",
 "ściągacz":"sťahovák", "rolki":"valčeky", "kapsel":"krytka", "kołki":"kolíky", "cieczy":"kvapaliny",
 "okładziny":"obloženie", "półosie":"poloosi", "dźwignia":"páka", "pomarańczowe":"oranžové",
 "plastików":"plastov", "przegubów":"kĺbov", "modele":"modely", "oś":"náprava", "górę":"hornú časť",
 "zaworowa":"ventilová", "dystansów":"rozširovacích podložiek", "lamp":"svetiel", "szare":"sivé", "nowość":"novinka",
 "regulowana":"nastaviteľná", "sprzęgłowy":"spojkový", "homologacja":"homologizácia", "ciężarki":"závažia",
 "bezprzewodowy":"bezdrôtový", "wiele":"viaceré", "wyciągarka":"navijak", "krótki":"krátky", "wszystkie":"všetky",
 "quady":"ATV", "napędowa":"hnacia", "kanistrów":"kanistrov", "stelaż":"rám", "wycieraczka":"stierač",
 "wyświetlacz":"displej", "dynamiczne":"dynamické", "zderzak":"nárazník", "elektryczne":"elektrické",
 "przeciw":"proti", "podświetlenie":"podsvietenie", "korbowego":"kľukového", "tarcze":"kotúče",
 "sprzęgłowe":"spojkové", "przekładki":"lamely", "filtra":"filtra", "ręcznego":"ručného", "kontroler":"riadiaca jednotka",
 "alternatora":"alternátora", "hamulcowej":"brzdovej", "wzmacniana":"zosilnená", "zielone":"zelené", "żarówka":"žiarovka",
 "podwójne":"dvojité", "przełączników":"prepínačov", "żółty":"žltý", "zapłonowy":"zapaľovací",
 "sintermetalowe":"sintrované", "przekładnia":"prevodovka", "ssący":"sací", "wydechowy":"výfukový",
 "pełna":"plná", "linka":"lanko", "zabezpieczenie":"poistka", "sworznia":"čapu", "amortyzatory":"tlmiče",
 "gumy":"gumové diely", "wirnik":"rotor", "pasek":"remeň", "sztyca":"driek", "przewód":"kábel", "zacisk":"strmeň",
 "szczeki":"čeľuste", "hamulcowe":"brzdové", "macphersona":"MacPherson", "haka":"háku", "uszczelniaczami":"guferami",
 "długie":"dlhé", "zawieszenia":"zavesenia", "szkło":"sklo", "niska":"nízka", "opon":"pneumatík",
 "dekiel":"kryt", "wyjście":"výstup", "boczne":"bočné", "aluminiowym":"hliníkovým", "oparciem":"operadlom",
 "śruba":"skrutka", "czujnikiem":"snímačom", "pojazdy":"vozidlá", "głowicy":"hlavy", "złącze":"konektor",
 "pomarańczowy":"oranžový", "skrzyni":"prevodovky", "stalowy":"oceľový", "magnesowe":"magnetické",
 "podgrzewane":"vyhrievané", "układu":"systému", "listwy":"rampy", "zasilającej":"napájacej",
 "bagażnik":"nosič", "zasilania":"napájania", "wieloklinem":"drážkovaním", "podświetlana":"podsvietená",
 "i":"a", "w":"v", "we":"v", "ze":"so",
 "kulisty":"guľový", "zaworowy":"ventilový", "zaworowa":"ventilová", "zaworowe":"ventilové", "zaworowej":"ventilov",
 "opakowanie":"balenie", "hamulcem":"brzdou", "mokrym":"mokrou", "dolne":"dolné", "nowe":"nový", "nowa":"nová", "nowy":"nový",
 "tworzywo":"materiál", "sztuczne":"plastový", "czujnika":"snímača", "mocowaniami":"držiakmi", "sztuk":"kusov",
 "termometr":"teplomer", "czujnikami":"snímačmi", "podgrzewany":"vyhrievaný", "kciuk":"palec", "wtyczki":"konektora",
 "sterownik":"ovládač", "podgrzewanych":"vyhrievaných", "manetek":"rukovätí", "punktowe":"bodové", "dwupozycyjny":"dvojpolohový",
 "sterowane":"ovládané", "smartfonem":"smartfónom", "silniki":"motory", "tlaku":"tlaku", "regulowany":"nastaviteľný",
 "homologacyjny":"homologizačný", "drzwiowy":"dverový", "inteligentne":"inteligentné", "boczne":"bočné", "serii":"série",
 "ryflowana":"protišmyková", "składane":"skladacie", "aluminium":"hliník", "alternatora":"alternátora", "czarno":"čierno",
 "napedowego":"hnacieho", "szybkiego":"rýchleho", "otwierania":"otvárania", "radiowy":"rádiový", "sterownika":"ovládača",
 "pojazdu":"vozidla", "przeprawowych":"terénnych", "rozstawem":"roztečou", "aluminiowe":"hliníkové", "blacha":"povrch",
}
POLISH_MARKERS = re.compile(r"\b(?:przedni|przednia|tylny|tylna|lewy|lewa|prawy|prawa|łożysk\w*|uszczelk\w*|wahacz\w*|rozrusznik\w*|wyciągark\w*|kierownicz\w*|przełącznik\w*|włącznik\w*|paliwa|powietrza|silnika|zamiennik|odpowiednik|uchwyt\w*|chromowan\w*|srebrn\w*|panewk\w*|przewod\w*|drzwi|torb\w*|mocowaniem|przelotow\w*|poszerzenia|syntetyczn\w*|gumowe|lub|oraz)\b|[ąćęłńóśźż]", re.I)

def dec(v):
 try: return Decimal((v or "0").strip().replace(",", "."))
 except InvalidOperation: return Decimal(0)

def fold(s):
 s=s.translate(str.maketrans("ŁłĐđØø", "LlDdOo"))
 return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c))
def stock_amount(v):
 s=(v or "0").strip(); return max(Decimal(0), dec(s[1:] if s.startswith(">") else s))
def markup(c):
 for lim, rate in ((10,70),(20,60),(30,50),(50,40),(100,30),(200,25)):
  if c <= lim: return Decimal(rate)/100
 return Decimal(".20")
def round_up_to_90(v):
 n=v.to_integral_value(rounding=ROUND_CEILING)-1; x=n+Decimal(".90")
 return (x if x >= v else x+1).quantize(Decimal(".01"))
def selling_price(pln, rate):
 c=pln/rate if pln>0 and rate>0 else Decimal(0)
 return round_up_to_90(c*(1+markup(c))) if c else Decimal(0)

def exchange_rate():
 if dec(os.getenv("PLN_PER_EUR"))>0: return dec(os.getenv("PLN_PER_EUR"))
 req=urllib.request.Request(ECB_URL,headers={"User-Agent":"AMDPRO-feed/2.0"})
 with urllib.request.urlopen(req,timeout=30) as r: root=ET.fromstring(r.read())
 for n in root.iter():
  if n.attrib.get("currency")=="PLN": return dec(n.attrib.get("rate"))
 raise RuntimeError("PLN rate missing")

def download(url, out, required):
 last=""
 for attempt in range(1,5):
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; AMDPRO-feed/2.0)","Accept":"text/csv,text/plain,*/*","Cache-Control":"no-cache"})
   with urllib.request.urlopen(req,timeout=180) as r: data=r.read()
   header=set(data.decode("utf-8-sig",errors="replace").splitlines()[0].split(";"))
   if not required <= header: raise RuntimeError("unexpected CSV header")
   out.write_bytes(data); return
  except (OSError,RuntimeError,IndexError) as e:
   last=str(e)
   if attempt<4: time.sleep(attempt*5)
 raise RuntimeError(f"supplier download failed: {last}")

def rows(path):
 with path.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f,delimiter=";"))
def source_path(r): return " > ".join((r.get(f"Kategoria_{i}_nazwa") or "").strip() for i in range(1,11) if (r.get(f"Kategoria_{i}_nazwa") or "").strip())
def category_for(r):
 name=fold(r.get("Nazwa_produktu") or ""); path=fold(source_path(r))
 priority=[
  (r"KOMINIARK", "Oblečenie / Motokrosové oblečenie / Termoprádlo"),
  (r"NAKLEJ", "Príslušenstvo a depo / Doplnky na motorku / Polepy a nálepky"),
  (r"DYSTANS", f"{A} / Kolesá a pneumatiky"),
  (r"CYLIND", f"{A} / Motor / Valce a hlavy"),
  (r"KROCIEC SS", f"{A} / Palivová sústava / Karburátory"),
  (r"STABILIZATOR|POLPANEW", f"{A} / Riadenie a podvozok / Puzdrá a opravné sady podvozka"),
  (r"SZYB|WYCIERACZ|DRZWI|GRILL|STELAZ", f"{A} / Karoséria a ochranné prvky / Plasty a kapotáže"),
  (r"POKRYW.*PASK|OBUDOW.*PASK", f"{A} / Motor / Kryty motora"),
  (r"PODUSZK.*SILN|GUM.*MOCOWAN.*SILN", f"{A} / Motor / Ostatné diely motora"),
  (r"KRANIK.*PALIW", f"{A} / Palivová sústava / Palivové ventily a hadice"),
  (r"KOREK.*PALIW", f"{A} / Palivová sústava / Palivové nádrže"),
  (r"ZWROTNIC", f"{A} / Riadenie a podvozok / Čapy riadenia"),
  (r"HELIX", f"{A} / Prevodovka a spojka / Variátory"),
  (r"SZARPAK", f"{A} / Elektrika a zapaľovanie / Štartéry"),
  (r"MODUL|KONTROLER", f"{A} / Elektrika a zapaľovanie / CDI a riadiace jednotky"),
  (r"CYLINDEREK HAMULC", f"{A} / Brzdy / Brzdové valce"),
  (r"POMP.*OLEJ|WIRNIK.*POMP", f"{A} / Motor / Ostatné diely motora"),
  (r"MAGNETO", f"{A} / Elektrika a zapaľovanie / Alternátory a statory"),
  (r"NAJAZD", "Príslušenstvo a depo / Doplnky na ATV/UTV"),
  (r"MOCOWAN.*NAWIGAC", "Príslušenstvo a depo / Doplnky na ATV/UTV / Držiaky a nosiče"),
  (r"SZCZEKI HAMULC",f"{A} / Brzdy / Brzdové platničky"),
  (r"LOZYSK.*(PIAST|KOL)",f"{A} / Kolesá a pneumatiky / Ložiská kolies"),
  (r"PRZELACZN|WLACZN|STACYJK",f"{A} / Elektrika a zapaľovanie / Ovládače a vypínače"),
  (r"PROWADNIC.*LANCUCH", "Príslušenstvo a depo / Chrániče motorky / Vodítka reťaze"),
 ]
 for pattern,target in priority+RULES:
  if re.search(pattern,name): return target, True
 for pattern,target in priority+RULES:
  if re.search(pattern,path): return target, True
 return ROOT, False

def translate_title(text):
 text=html.unescape(re.sub(r"<[^>]+>"," ",text or ""))
 for pattern,replacement in PHRASES: text=re.sub(pattern,replacement,text,flags=re.I)
 def word(m): return WORDS.get(m.group(0).lower(),m.group(0))
 text=re.sub(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+",word,text)
 # Do not publish leftover Polish inflection. Keep brands, models, numbers and
 # already translated technical words, but drop unresolved Polish tokens.
 text=" ".join(t for t in text.split() if not POLISH_MARKERS.search(t))
 text=re.sub(r"\s+([,.;:])",r"\1",re.sub(r"\s+"," ",text)).strip(" -,.;")
 # Natural Slovak word order for the most frequent ATV chassis constructions.
 side={"predný":"predné","zadný":"zadné","horný":"horné","dolný":"dolné","ľavý":"ľavé","pravý":"pravé"}
 def arm(m):
  adjectives=" ".join(side.get(x.lower(),x) for x in m.groups() if x)
  return f"{adjectives.capitalize()} rameno"
 text=re.sub(r"(?i)\brameno\s+(predný|zadný)(?:\s+(horný|dolný))?(?:\s+(ľavý|pravý))?\b",arm,text)
 text=re.sub(r"(?i)\bopravná sada ramena (horného|dolného)\b",r"opravná sada \1 ramena",text)
 text=re.sub(r"(?i)\bčap ramena (horný|dolný)\b",r"\1 čap ramena",text)
 text=re.sub(r"(?i)\bguľový čap náboja kolesa (horný|dolný)\b",r"\1 guľový čap náboja kolesa",text)
 text=re.sub(r"(?i)\bkukla štandardná farba čierny\b","štandardná kukla – čierna",text)
 return text[:1].upper()+text[1:]

def product_name(r,category):
 translated=translate_title(r.get("Nazwa_produktu") or "")
 code=(r.get("Nr_katalogowy") or "").strip(); label=category.rsplit(" / ",1)[-1]
 if len(translated)<8: translated=f"{label} {(r.get('Producent') or '').strip()}"
 if code.lower() not in translated.lower(): translated=f"{translated} – {code}"
 return translated[:250]

def reference_codes(text,product_code):
 result=[]
 for token in re.findall(r"(?<![\w])(?=[A-Z0-9./-]{4,})(?=[A-Z0-9./-]*\d)[A-Z0-9]+(?:[./-][A-Z0-9]+)+(?![\w])",(text or "").upper()):
  if not re.search(r"[A-Z]",token): continue
  if token != product_code.upper() and token not in result: result.append(token)
  if len(result)>=16: break
 return result

def description_lines(value):
 text=html.unescape(value or "")
 text=re.sub(r"(?i)<\s*(?:br\s*/?|/p|/li|/div|/h[1-6])\s*>","\n",text)
 text=re.sub(r"<[^>]+>"," ",text)
 return [re.sub(r"\s+"," ",line).strip(" \t-*•:;") for line in text.splitlines() if re.sub(r"\s+"," ",line).strip(" \t-*•:;")]

def translate_detail(text):
 result=translate_title(text)
 replacements={
  "zastosowanie":"kompatibilita", "pasuje do":"vhodné pre", "producent":"výrobca",
  "materiał":"materiál", "wymiary":"rozmery", "długość":"dĺžka", "szerokość":"šírka",
  "wysokość":"výška", "waga":"hmotnosť", "kolor":"farba", "rozmiar":"veľkosť",
  "przód":"predná časť", "tył":"zadná časť", "rear":"zadná", "front":"predná",
 }
 for source,target in replacements.items(): result=re.sub(rf"\b{source}\b",target,result,flags=re.I)
 result=re.sub(r"\s+"," ",result).strip(" ,.;:-")
 return result

def technical_details(value):
 details=[]
 labels={
  "materiał":"Materiál", "kolor":"Farba", "rozmiar":"Veľkosť", "wymiary":"Rozmery",
  "długość":"Dĺžka", "szerokość":"Šírka", "wysokość":"Výška", "waga":"Hmotnosť",
  "średnica":"Priemer", "grubość":"Hrúbka", "gwint":"Závit", "rozstaw":"Rozteč",
  "napięcie":"Napätie", "moc":"Výkon", "pojemność":"Objem", "udźwig":"Nosnosť",
 }
 for line in description_lines(value):
  match=re.match(r"(?i)^([^:]{2,28})\s*:\s*(.{1,120})$",line)
  if not match: continue
  key=match.group(1).strip().lower(); label=next((sk for pl,sk in labels.items() if key==pl or key.startswith(pl+" ")),None)
  if not label: continue
  translated=translate_detail(match.group(2))
  if translated and not POLISH_MARKERS.search(translated):
   pair=(label,translated)
   if pair not in details: details.append(pair)
  if len(details)>=12: break
 return details

def compatible_models(value):
 lines=description_lines(value); collecting=False; models=[]
 start=re.compile(r"(?i)^(?:zastosowanie|pasuje do|dedykowan\w* do|kompatybiln\w* z)\b")
 stop=re.compile(r"(?i)^(?:dane techniczne|właściwości|skład zestawu|opis|uwaga|materiał|kolor|wymiary)\b")
 for line in lines:
  if start.search(line):
   collecting=True
   line=start.sub("",line).strip(" :")
  elif collecting and stop.search(line):
   break
  if not collecting or not line or not re.search(r"\d",line): continue
  # Diagram labels after a dash are not part of the vehicle designation.
  line=re.sub(r"\s+-\s+(?:Rear|Front|Steering|Prop|Crankcase|Suspension|Brake|Caliper).*$","",line,flags=re.I)
  translated=translate_detail(line)
  if len(translated)>180 or POLISH_MARKERS.search(translated): continue
  if translated not in models: models.append(translated)
  if len(models)>=60: break
 return models

def description(name,r):
 code=(r.get("Nr_katalogowy") or "").strip(); maker=(r.get("Producent") or "Moto-Maniak").strip()
 refs=reference_codes((r.get("Nazwa_produktu") or "")+" "+(r.get("Opis") or ""),code)
 details=technical_details(r.get("Opis") or ""); models=compatible_models(r.get("Opis") or "")
 parts=[f"<h2>{html.escape(name)}</h2>","<h3>Informácie o produkte</h3>","<ul>",f"<li>Katalógové číslo: <strong>{html.escape(code)}</strong></li>",f"<li>Výrobca: {html.escape(maker)}</li>"]
 if refs: parts.append(f"<li>OEM a referenčné čísla: {html.escape(', '.join(refs))}</li>")
 parts.append("</ul>")
 if details:
  parts.append("<h3>Technické údaje</h3><ul>")
  parts.extend(f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>" for label,value in details)
  parts.append("</ul>")
 if models:
  parts.append("<h3>Kompatibilita</h3><ul>")
  parts.extend(f"<li>{html.escape(model)}</li>" for model in models)
  parts.append("</ul>")
 parts.append("<p>Pred objednaním porovnajte katalógové alebo OEM číslo a overte zhodu s presným modelom, ročníkom a verziou vozidla.</p>")
 return "".join(parts)

def build_feed(catalog_path,stock_path,destination,rate):
 current={(r.get("Nr_katalogowy") or "").strip():r for r in rows(stock_path)}
 counts={"products":0,"visible":0,"hidden":0,"specific_category":0,"root_category":0,"duplicate_codes":0,"invalid":0}; occurrences={}
 destination.parent.mkdir(parents=True,exist_ok=True); tmp=destination.with_suffix(".xml.tmp")
 with tmp.open("wb") as out:
  out.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
  for r in rows(catalog_path):
   if (r.get("Status") or "").strip().lower()!="tak": continue
   raw=(r.get("Nr_katalogowy") or "").strip(); s=current.get(raw); gross=dec((s or {}).get("Cena_brutto") or r.get("Cena_brutto"))
   if not raw or s is None or gross<=0: counts["invalid"]+=1; continue
   occurrences[raw]=occurrences.get(raw,0)+1; suffix=f"-{occurrences[raw]}" if occurrences[raw]>1 else ""
   if suffix: counts["duplicate_codes"]+=1
   amount=stock_amount(s.get("Ilosc_produktow")); visible=amount>0; category,specific=category_for(r); name=product_name(r,category)
   item=ET.Element("SHOPITEM")
   ET.SubElement(item,"NAME").text=name; ET.SubElement(item,"DESCRIPTION").text=description(name,r)
   ET.SubElement(item,"MANUFACTURER").text=(r.get("Producent") or "Moto-Maniak").strip()[:200]; ET.SubElement(item,"SUPPLIER").text="Moto-Maniak"
   ET.SubElement(item,"ITEM_TYPE").text="product"; ET.SubElement(item,"UNIT").text="ks"; ET.SubElement(item,"CODE").text=(PREFIX+raw+suffix)[:64]
   ean=(r.get("Kod_ean") or "").strip()
   if ean.isdigit() and 8<=len(ean)<=14: ET.SubElement(item,"EAN").text=ean
   cats=ET.SubElement(item,"CATEGORIES"); ET.SubElement(cats,"CATEGORY").text=category.replace(" / "," > ")
   urls=[]
   for field in ["Zdjecie_glowne"]+[f"Zdjecie_dodatkowe_{i}" for i in range(1,11)]:
    url=(r.get(field) or "").strip()
    if url.startswith(("http://","https://")) and url not in urls: urls.append(url)
   if urls:
    images=ET.SubElement(item,"IMAGES")
    for url in urls: ET.SubElement(images,"IMAGE").text=url
   ET.SubElement(item,"VISIBILITY").text="visible" if visible else "hidden"
   ET.SubElement(ET.SubElement(item,"STOCK"),"AMOUNT").text=str(amount.quantize(Decimal(1)))
   ET.SubElement(item,"AVAILABILITY_IN_STOCK").text="Skladom u dodávateľa"; ET.SubElement(item,"AVAILABILITY_OUT_OF_STOCK").text="Momentálne nedostupné"
   ET.SubElement(item,"CURRENCY").text="EUR"; ET.SubElement(item,"PRICE_VAT").text=f"{selling_price(gross,rate):.2f}"
   out.write(ET.tostring(item,encoding="utf-8")+b"\n")
   counts["products"]+=1; counts["visible" if visible else "hidden"]+=1; counts["specific_category" if specific else "root_category"]+=1
  out.write(b"</SHOP>\n")
 ET.parse(tmp); tmp.replace(destination); return counts

def main():
 output=Path("public/motomaniak-update.xml"); status=Path("public/motomaniak-status.json")
 with tempfile.TemporaryDirectory() as d:
  d=Path(d); catalog=d/"catalog.csv"; stock=d/"stock.csv"
  download(os.getenv("MOTOMANIAK_CATALOG_URL",CATALOG_URL),catalog,{"Nr_katalogowy","Nazwa_produktu","Status"})
  download(os.getenv("MOTOMANIAK_STOCK_URL",STOCK_URL),stock,{"Nr_katalogowy","Cena_brutto","Ilosc_produktow"})
  rate=exchange_rate(); counts=build_feed(catalog,stock,output,rate)
 status.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"source":"Moto-Maniak catalog and hourly stock CSV","pln_per_eur":str(rate),"price_vat_added_again":False,**counts},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(f"Wrote {counts['products']} products to {output}")

if __name__=="__main__": main()
