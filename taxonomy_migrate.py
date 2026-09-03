#!/usr/bin/env python3
"""Remap a complete Shoptet export to the reviewed AMDPRO taxonomy.

The source is never changed. Classification is deterministic and produces a
review CSV for every low-confidence or conflicting decision.
"""

from __future__ import annotations

import argparse
import collections
import csv
import functools
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from join_supplier_names import supplier_index


def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = value.translate(str.maketrans({"ł": "l", "đ": "d", "ß": "ss"}))
    return " ".join(value.split())


@functools.lru_cache(maxsize=None)
def compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


@dataclass(frozen=True)
class Rule:
    leaf: str
    patterns: tuple[str, ...]


RULES = (
    # Rider products must win before technical words such as filter or chain.
    Rule("Oblečenie > MX oblečenie > Dresy", (r"\bdres", r"jersey")),
    Rule("Oblečenie > MX oblečenie > Nohavice", (r"moto nohavic", r"mx nohavic", r"spodnie motocyk")),
    Rule("Oblečenie > MX oblečenie > Rukavice", (r"\brukavic", r"rekawic")),
    Rule("Oblečenie > MX oblečenie > Bundy", (r"moto bund", r"mx bund", r"kurtk")),
    Rule("Oblečenie > MX oblečenie > Termoprádlo", (r"termoprad", r"termo prad", r"termicky", r"termoaktiv")),
    Rule("Oblečenie > Voľný čas > Tričká", (r"\btrick", r"t-shirt")),
    Rule("Oblečenie > Voľný čas > Mikiny", (r"\bmikin", r"bluz")),
    Rule("Oblečenie > Voľný čas > Čiapky a šiltovky", (r"ciapk", r"siltov", r"czapk")),
    Rule("Výstroj > Prilby a okuliare > Moto okuliare", (r"moto okuliar", r"mx okuliar", r"gogle")),
    Rule("Výstroj > Prilby a okuliare > Náhradné sklá a diely prilieb", (r"plexi.*prilb", r"sklo.*prilb", r"diel.*prilb", r"prislusenstvo.*prilb")),
    Rule("Výstroj > Prilby a okuliare > Prilby", (r"\bprilb", r"\bhelma", r"\bkask")),
    Rule("Výstroj > Čižmy > Náhradné diely čižiem", (r"diel.*cizm", r"prack.*cizm", r"podrazk.*cizm")),
    Rule("Výstroj > Čižmy > Čižmy", (r"\bcizm", r"moto obuv", r"buty motocyk")),
    Rule("Výstroj > Chrániče > Chrániče kolien", (r"chranic.*kolen", r"nakolenn")),
    Rule("Výstroj > Chrániče > Chrániče lakťov", (r"chranic.*lakt", r"nalokiet")),
    Rule("Výstroj > Chrániče > Chrániče krku", (r"chranic.*krk", r"krčna chrbt")),
    Rule("Výstroj > Chrániče > Chrániče trupu", (r"chranic.*trup", r"hrudn.*chran", r"pancier")),
    Rule("Výstroj > Chrániče > Ľadvinové pásy", (r"ladvin", r"pas nerk")),
    Rule("Príslušenstvo a náradie > Moto príslušenstvo > Batožina a kufre", (r"\bkufor", r"\bkufre", r"\btaska", r"\bbatozin", r"plecak")),
    Rule("Príslušenstvo a náradie > Moto príslušenstvo > Držiaky telefónov a navigácie", (r"drziak.*telefon", r"navigac", r"gps")),
    Rule("Príslušenstvo a náradie > Moto príslušenstvo > Zámky a zabezpečenie", (r"\bzamok", r"alarm", r"zabezpec")),
    Rule("Príslušenstvo a náradie > Moto príslušenstvo > Upínacie popruhy", (r"upinac.*popruh", r"transport.*popruh")),
    Rule("Príslušenstvo a náradie > Dielenské náradie > Servisné stojany", (r"stojan.*moto", r"servisny stojan", r"montazny stojan")),
    Rule("Príslušenstvo a náradie > Dielenské náradie > Montáž pneumatík", (r"prezuv", r"montpaka", r"montaz.*pneumat")),
    Rule("Príslušenstvo a náradie > Dielenské náradie > Nabíjačky batérií", (r"nabijack.*bater", r"nabijack.*akumulator")),
    Rule("Príslušenstvo a náradie > Dielenské náradie > Kľúče a sťahováky", (r"\bkluc", r"stahovak", r"naradie")),
    # Wheel and chassis.
    Rule("Kolesá a pneumatiky > Pneumatiky", (r"\bpneumatik", r"\bopony", r"\bopona")),
    Rule("Kolesá a pneumatiky > Duše", (r"\bdus(e|a|u|ou)\b", r"\bdetk")),
    Rule("Kolesá a pneumatiky > Bezdušové systémy a mousse", (r"tubliss", r"mousse", r"bezduš")),
    Rule("Kolesá a pneumatiky > Ložiská kolies", (r"lozisk.*koles", r"łożysk.*koł")),
    Rule("Kolesá a pneumatiky > Ráfiky a špice", (r"\brafik", r"\bspic", r"felg", r"szprych")),
    Rule("Kolesá a pneumatiky > Ventily a príslušenstvo kolies", (r"ventil.*koles", r"zavazie.*koles", r"rim lock")),
    Rule("Podvozok > Predné vidlice", (r"predn.*vidlic", r"teleskop", r"uszczelniacz.*zawies")),
    Rule("Podvozok > Zadné tlmiče", (r"zadn.*tlmic", r"centraln.*tlmic", r"amortyzator")),
    Rule("Podvozok > Kyvné vidlice", (r"kyvn.*vidlic", r"wahacz")),
    Rule("Podvozok > Prepákovanie", (r"prepak", r"kiwak")),
    Rule("Podvozok > Ložiská tlmičov", (r"lozisk.*tlmic", r"lozisk.*prepak")),
    Rule("Podvozok > Ložiská krku riadenia", (r"lozisk.*krk", r"łożysk.*główk")),
    Rule("Podvozok > Stupačky", (r"stupack", r"podnoz", r"podnóż")),
    # Controls and body.
    Rule("Riadidlá a ovládanie > Chrániče riadidiel, rúk a páčok", (r"chranic.*ruk", r"chranic.*pack", r"handguard")),
    Rule("Riadidlá a ovládanie > Držiaky a vyvýšenia riadidiel", (r"vyvys.*riad", r"drziak.*riad", r"podwyz.*kier")),
    Rule("Riadidlá a ovládanie > Rukoväte a rýchlopaly", (r"rukovat", r"rychlopal", r"rolgaz", r"manetk")),
    Rule("Riadidlá a ovládanie > Riadidlá", (r"\briadidl", r"kierownic")),
    Rule("Riadidlá a ovládanie > Lanká", (r"\blanko", r"\blanka", r"\blink[aiy]")),
    Rule("Riadidlá a ovládanie > Radiace páčky", (r"radiac.*pack", r"dzwign.*zmian")),
    Rule("Riadidlá a ovládanie > Štartovacie páky", (r"start.*pak", r"nakopav")),
    Rule("Riadidlá a ovládanie > Páčky a objímky", (r"\bpack", r"objimk", r"dzwign")),
    Rule("Karoséria a plasty > Sedadlá, peny a poťahy", (r"sedadl", r"potah.*sed", r"pena.*sed", r"siedzen", r"gabk.*siedz")),
    Rule("Karoséria a plasty > Plexi a kapotáže", (r"\bplexi", r"kapotaz")),
    Rule("Karoséria a plasty > Blatníky a bočné plasty", (r"blatnik", r"plastik", r"boczk")),
    Rule("Karoséria a plasty > Kryty a chrániče motora", (r"kryt.*motor", r"chranic.*motor", r"oslon.*silnik")),
    Rule("Karoséria a plasty > Zrkadlá", (r"zrkadl", r"lusterk")),
    Rule("Karoséria a plasty > Polepy a nálepky", (r"polep", r"nalep", r"naklejk")),
    Rule("Karoséria a plasty > Plasty podľa značky motocykla", (r"karoser", r"nadwoz", r"\bplasty\b")),
    # Brakes and drive.
    Rule("Brzdy > Brzdové platničky", (r"brzdov.*plat", r"brzdov.*dostic", r"klock.*hamul")),
    Rule("Brzdy > Brzdové kotúče", (r"brzdov.*kotuc", r"tarc.*hamul")),
    Rule("Brzdy > Brzdové čeľuste", (r"brzdov.*celust", r"szczek.*hamul")),
    Rule("Brzdy > Brzdové hadice", (r"brzdov.*hadic", r"przewod.*hamul")),
    Rule("Brzdy > Brzdové strmene", (r"brzdov.*strmen", r"zacisk.*hamul")),
    Rule("Brzdy > Brzdové pumpy", (r"brzdov.*pump", r"hlavn.*brzd.*valec", r"pompa.*hamul")),
    Rule("Brzdy > Opravné sady bŕzd", (r"oprav.*sad.*brzd", r"repas.*brzd", r"zestaw.*napraw.*hamul")),
    Rule("Brzdy > Adaptéry brzdových kotúčov", (r"adapter.*brzd", r"adapter.*kotuc")),
    Rule("Pohon a reťazové sady > Vodítka a kladky reťaze", (r"voditk.*retaz", r"kladk.*retaz", r"slizg.*lanc")),
    Rule("Pohon a reťazové sady > Skrutky rozety", (r"skrutk.*rozet",)),
    Rule("Pohon a reťazové sady > Predné reťazové kolieska", (r"predn.*retaz.*kol", r"vyvodov.*kol", r"zebatk.*przod")),
    Rule("Pohon a reťazové sady > Zadné rozety", (r"zadn.*rozet", r"\brozet", r"zebatk.*tyl")),
    Rule("Pohon a reťazové sady > Reťazové sady", (r"retazov.*sad", r"retazov.*suprav", r"zestaw.*naped")),
    Rule("Pohon a reťazové sady > Reťaze", (r"\bretaz", r"\blancuch")),
    Rule("Pohon a reťazové sady > Kardany a hnacie hriadele", (r"\bkardan", r"hnac.*hriad", r"wal.*naped")),
    # Engine, fuel and cooling.
    Rule("Motor > Piesty a piestne sady", (r"\bpiest", r"tłok", r"tlok")),
    Rule("Motor > Valce a hlavy", (r"\bvalec", r"\bvalce", r"hlav.*valc", r"cylind", r"glowic")),
    Rule("Motor > Ložiská motora", (r"lozisk.*motor", r"lozysk.*silnik", r"lozisk.*kluk", r"lozysk.*wal.*korbow")),
    Rule("Motor > Ojnice a kľukové hriadele", (r"\bojnic", r"klukov.*hriad", r"korbowod", r"wal.*korbow")),
    Rule("Motor > Ventily a ventilové sady", (r"\bventil", r"zawor")),
    Rule("Motor > Rozvody", (r"\brozvod", r"vackov.*hriad", r"rozrzad")),
    Rule("Motor > Tesnenia motora", (r"tesnen", r"uszczelk")),
    Rule("Motor > Guferá", (r"\bgufer", r"uszczelniacz")),
    Rule("Motor > Spojky a spojkové diely", (r"\bspojk", r"sprzegl")),
    Rule("Motor > Prevodovka", (r"prevodov", r"skrzyn.*bieg")),
    Rule("Palivový a chladiaci systém > Karburátory a diely karburátorov", (r"karbur", r"gaznik", r"gaźnik")),
    Rule("Palivový a chladiaci systém > Vstrekovanie paliva", (r"vstrek", r"wtrysk")),
    Rule("Palivový a chladiaci systém > Palivové čerpadlá", (r"palivov.*cerpad", r"pompa.*paliw")),
    Rule("Palivový a chladiaci systém > Palivové kohúty a nádrže", (r"palivov.*kohut", r"palivov.*nadrz", r"kranik", r"bak paliw")),
    Rule("Palivový a chladiaci systém > Vodné pumpy a opravné sady", (r"vodn.*pump", r"cerpad.*vod", r"pompa.*wod")),
    Rule("Palivový a chladiaci systém > Chladiče", (r"\bchladic", r"chlodnic")),
    Rule("Palivový a chladiaci systém > Hadice a termostaty", (r"termostat", r"hadic.*chlad", r"przewod.*chlod")),
    # Electrical, consumables and exhaust.
    Rule("Elektrické diely > Zapaľovacie sviečky a fajky", (r"zapalovac.*sviec", r"\bsviecka", r"fajk", r"swiec")),
    Rule("Elektrické diely > Batérie", (r"\bbateri", r"akumulator")),
    Rule("Elektrické diely > Štartéry a štartovacie relé", (r"\bstarter", r"startov.*rele")),
    Rule("Elektrické diely > Alternátory a regulátory", (r"alternator", r"regulator.*napat", r"stator")),
    Rule("Elektrické diely > Zapaľovanie", (r"zapalov", r"cevk", r"zaplon")),
    Rule("Elektrické diely > Snímače a spínače", (r"\bsnimac", r"\bsenzor", r"\bspinac", r"czujnik")),
    Rule("Elektrické diely > Ovládače a vypínače", (r"ovladac", r"vypinac", r"przelacznik")),
    Rule("Elektrické diely > Osvetlenie a smerovky", (r"svetlo", r"lamp", r"smerov", r"kierunkowskaz")),
    Rule("Elektrické diely > Kabeláž, žiarovky a poistky", (r"kabel", r"kabl", r"ziarov", r"poistk", r"bezpiecznik")),
    Rule("Elektrické diely > Merače motohodín", (r"motohodin", r"licznik.*godzin")),
    Rule("Filtre > Olejové filtre", (r"olejov.*filter", r"filtr.*olej")),
    Rule("Filtre > Vzduchové filtre", (r"vzduchov.*filter", r"filtr.*powietrz")),
    Rule("Filtre > Palivové filtre", (r"palivov.*filter", r"filtr.*paliw")),
    Rule("Oleje a kvapaliny > Motorové oleje 2T", (r"olej.*\b2t\b", r"olej.*dwusuw")),
    Rule("Oleje a kvapaliny > Motorové oleje 4T", (r"olej.*\b4t\b", r"olej.*czterosuw")),
    Rule("Oleje a kvapaliny > Vidlicové a tlmičové oleje", (r"vidlicov.*olej", r"tlmic.*olej", r"fork oil")),
    Rule("Oleje a kvapaliny > Prevodové oleje", (r"prevodov.*olej", r"gear oil")),
    Rule("Oleje a kvapaliny > Hydraulické oleje", (r"hydraul.*olej", r"hydraulic oil")),
    Rule("Oleje a kvapaliny > Brzdové kvapaliny", (r"brzdov.*kvapalin", r"brake fluid")),
    Rule("Oleje a kvapaliny > Chladiace kvapaliny", (r"chladiac.*kvapalin", r"coolant", r"antifreeze")),
    Rule("Oleje a kvapaliny > Mazivá a vazelíny", (r"\bmaziv", r"vazelin", r"smar")),
    Rule("Oleje a kvapaliny > Servisná chémia a čističe", (r"\bcistic", r"chemia", r"odmast", r"cleaner")),
    Rule("Výfuky > Tesnenia a príslušenstvo výfukov", (r"tesnen.*vyfuk", r"prislusenstvo.*vyfuk", r"uszczelk.*wydech")),
    Rule("Výfuky > Koncovky výfukov", (r"koncovk.*vyfuk", r"tlmic.*vyfuk")),
    Rule("Výfuky > Zvody", (r"\bzvod", r"kolektor.*wydech")),
    Rule("Výfuky > Výfuky", (r"\bvyfuk", r"uklad.*wydech")),
)

ATV_MARKERS = re.compile(r"\b(atv|utv|stvorkolk|quad|cfmoto|cforce|zforce|uforce|can[ -]?am|polaris|sportsman|scrambler|renegade|outlander|grizzly|bruin|kodiak|kingquad|kfx|kvf|trx ?[0-9]|foreman|rincon)\b")
ATV_REWRITES = {
    "Kolesá a pneumatiky": "Kolesá a pneumatiky ATV/UTV",
    "Podvozok": "Podvozok a riadenie ATV/UTV",
    "Pohon a reťazové sady": "Pohon a prevodovka ATV/UTV",
    "Brzdy": "Brzdy ATV/UTV",
    "Motor": "Motor ATV/UTV",
    "Palivový a chladiaci systém": "Palivový a chladiaci systém ATV/UTV",
    "Elektrické diely": "Elektrické diely ATV/UTV",
    "Karoséria a plasty": "Karoséria a príslušenstvo ATV/UTV",
}

ATV_SPECIAL = (
    Rule("ATV/UTV > Pohon a prevodovka ATV/UTV > Variátorové remene", (r"variator.*remen", r"remen.*variator", r"pas.*naped")),
    Rule("ATV/UTV > Pohon a prevodovka ATV/UTV > Variátory a CVT", (r"\bvariator", r"\bcvt\b")),
    Rule("ATV/UTV > Pohon a prevodovka ATV/UTV > Diferenciály", (r"diferencial" ,)),
    Rule("ATV/UTV > Pohon a prevodovka ATV/UTV > Poloosy", (r"poloos",)),
    Rule("ATV/UTV > Pohon a prevodovka ATV/UTV > Kĺby a manžety", (r"\bklb", r"manzet")),
    Rule("ATV/UTV > Karoséria a príslušenstvo ATV/UTV > Navijaky", (r"navijak", r"winch")),
    Rule("ATV/UTV > Karoséria a príslušenstvo ATV/UTV > Pluhy", (r"\bpluh", r"radlic")),
    Rule("ATV/UTV > Karoséria a príslušenstvo ATV/UTV > Ťažné zariadenia", (r"tazn.*zariad", r"tazn.*gul")),
)


def classify(item: ET.Element, supplier: dict[str, str] | None = None) -> tuple[str, int, str, list[str]]:
    supplier = supplier or {}
    name = fold(" ".join((item.findtext("NAME") or "", supplier.get("supplier_name_pl", ""))))
    descriptions = fold(" ".join((item.findtext(tag) or "") for tag in ("SHORT_DESCRIPTION", "DESCRIPTION")))[:4000]
    categories = [fold(node.text or "") for node in item.findall("./CATEGORIES/CATEGORY")]
    supplier_category = fold(supplier.get("supplier_category_pl", ""))
    category_text = " | ".join(categories + ([supplier_category] if supplier_category else []))
    text = f"{name} | {category_text} | {descriptions}"
    is_atv = any(path.startswith("atv/utv") for path in categories) or bool(ATV_MARKERS.search(f"{name} {category_text}"))

    candidates: list[tuple[int, int, str, str]] = []
    active_rules = ATV_SPECIAL + RULES if is_atv else RULES
    for order, rule in enumerate(active_rules):
        score = 0
        evidence = []
        for pattern in rule.patterns:
            regex = compiled(pattern)
            if regex.search(name):
                score += 8
                evidence.append("name")
            if regex.search(category_text):
                score += 5
                evidence.append("category")
            if regex.search(descriptions):
                score += 1
                evidence.append("description")
        if score:
            candidates.append((score, -order, rule.leaf, "+".join(sorted(set(evidence)))))

    if not candidates:
        fallback = "ATV/UTV > Na ručnú kontrolu" if is_atv else "Motodiely > Na ručnú kontrolu"
        return fallback, 0, "no_rule", []
    candidates.sort(reverse=True)
    best = candidates[0]
    target = best[2]
    root = target.split(" > ", 1)[0]
    if target.startswith("ATV/UTV >"):
        pass
    elif is_atv and root in ATV_REWRITES:
        target = target.replace(root, "ATV/UTV > " + ATV_REWRITES[root], 1)
    elif root not in {"Oblečenie", "Výstroj", "Príslušenstvo a náradie", "Oleje a kvapaliny"}:
        target = "Motodiely > " + target
    alternatives = [candidate[2] for candidate in candidates[1:4] if candidate[0] >= best[0] - 2]
    confidence = best[0]
    reason = best[3]
    return target, confidence, reason, alternatives


def rewrite_categories(item: ET.Element, target: str, sale: bool) -> None:
    old = item.find("CATEGORIES")
    old_paths = [(node.text or "").strip() for node in item.findall("./CATEGORIES/CATEGORY")]
    compatibility_paths = [
        path for path in old_paths
        if "Diely podľa motocykla >" in path or "Diely podľa ATV >" in path
    ]
    insert_at = list(item).index(old) if old is not None else min(8, len(item))
    if old is not None:
        item.remove(old)
    container = ET.Element("CATEGORIES")
    category = ET.SubElement(container, "CATEGORY")
    category.text = target
    for path in dict.fromkeys(compatibility_paths):
        if path != target:
            compatibility = ET.SubElement(container, "CATEGORY")
            compatibility.text = path
    if sale:
        sale_category = ET.SubElement(container, "CATEGORY")
        sale_category.text = "Výpredaj"
    default = ET.SubElement(container, "DEFAULT_CATEGORY")
    default.text = target
    item.insert(insert_at, container)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--supplier-feed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.review.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    counts: collections.Counter[str] = collections.Counter()
    by_code, by_ean, _, _ = supplier_index(args.supplier_feed)
    reviewed = 0
    sales = 0

    with temporary.open("wb") as output, args.review.open("w", encoding="utf-8", newline="") as review:
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
        writer = csv.DictWriter(review, fieldnames=("code", "name", "old_categories", "proposed_category", "confidence", "reason", "alternatives", "problem"))
        writer.writeheader()
        for _, item in ET.iterparse(args.source, events=("end",)):
            if item.tag != "SHOPITEM":
                continue
            name = (item.findtext("NAME") or "").strip()
            code = (item.findtext("CODE") or "").strip()
            ean = (item.findtext("EAN") or "").strip()
            old = " | ".join((node.text or "").strip() for node in item.findall("./CATEGORIES/CATEGORY"))
            code_match = by_code.get(code)
            ean_match = by_ean.get(ean) if ean else None
            conflict = bool(code_match and ean_match and code_match["supplier_id"] != ean_match["supplier_id"])
            if conflict or not (code_match or ean_match):
                output.write(ET.tostring(item, encoding="utf-8", short_empty_elements=True))
                output.write(b"\n")
                counts["__preserved_manual_or_conflict__"] += 1
                item.clear()
                continue
            supplier_match = code_match or ean_match
            target, confidence, reason, alternatives = classify(item, supplier_match)
            sale = bool(re.search(r"\bvypredaj\b", fold(name)))
            rewrite_categories(item, target, sale)
            output.write(ET.tostring(item, encoding="utf-8", short_empty_elements=True))
            output.write(b"\n")
            counts[target] += 1
            sales += sale
            problem = ""
            if confidence < 8:
                problem = "low_confidence"
            elif alternatives:
                problem = "conflicting_rules"
            if "Na ručnú kontrolu" in target:
                problem = "unclassified"
            if problem:
                reviewed += 1
                writer.writerow({"code": code, "name": name, "old_categories": old, "proposed_category": target, "confidence": confidence, "reason": reason, "alternatives": " | ".join(alternatives), "problem": problem})
            item.clear()
        output.write(b"</SHOP>\n")
    ET.parse(temporary)
    temporary.replace(args.output)
    args.summary.write_text(json.dumps({"products": sum(counts.values()), "review_required": reviewed, "sale_products": sales, "target_categories": len(counts), "categories": counts.most_common()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
