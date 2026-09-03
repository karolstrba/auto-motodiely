#!/usr/bin/env python3
"""Replace generic names only when a safe Slovak name can be constructed."""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from join_supplier_names import GENERIC, supplier_index

TYPE_NAMES = {
    "Prilby": "Motocyklová prilba",
    "Pneumatiky": "Pneumatika",
    "Duše": "Duša",
    "Bezdušové systémy a mousse": "Bezdušový systém",
    "Ložiská kolies": "Sada ložísk kolesa",
    "Ráfiky a špice": "Diel kolesa",
    "Ventily a príslušenstvo kolies": "Príslušenstvo kolesa",
    "Predné vidlice": "Diel prednej vidlice",
    "Zadné tlmiče": "Diel zadného tlmiča",
    "Kyvné vidlice": "Diel kyvnej vidlice",
    "Prepákovanie": "Opravná sada prepákovania",
    "Ložiská tlmičov": "Sada ložísk tlmiča",
    "Ložiská krku riadenia": "Sada ložísk krku riadenia",
    "Stupačky": "Stupačky",
    "Reťazové sady": "Reťazová sada",
    "Reťaze": "Reťaz",
    "Predné reťazové kolieska": "Predné reťazové koliesko",
    "Zadné rozety": "Zadná rozeta",
    "Vodítka a kladky reťaze": "Vodítko alebo kladka reťaze",
    "Skrutky rozety": "Sada skrutiek rozety",
    "Kardany a hnacie hriadele": "Kardan alebo hnací hriadeľ",
    "Brzdové platničky": "Brzdové platničky",
    "Brzdové kotúče": "Brzdový kotúč",
    "Brzdové čeľuste": "Brzdové čeľuste",
    "Brzdové hadice": "Brzdová hadica",
    "Brzdové strmene": "Diel brzdového strmeňa",
    "Brzdové pumpy": "Diel brzdovej pumpy",
    "Opravné sady bŕzd": "Opravná sada bŕzd",
    "Adaptéry brzdových kotúčov": "Adaptér brzdového kotúča",
    "Riadidlá": "Riadidlá",
    "Rukoväte a rýchlopaly": "Rukoväť alebo rýchlopal",
    "Lanká": "Ovládacie lanko",
    "Páčky a objímky": "Diel ovládacej páčky",
    "Držiaky a vyvýšenia riadidiel": "Držiak alebo vyvýšenie riadidiel",
    "Chrániče riadidiel, rúk a páčok": "Chránič riadidiel alebo páčok",
    "Radiace páčky": "Radiaca páčka",
    "Štartovacie páky": "Štartovacia páka",
    "Piesty a piestne sady": "Piestna sada",
    "Valce a hlavy": "Diel valca alebo hlavy motora",
    "Ložiská motora": "Sada ložísk motora",
    "Ojnice a kľukové hriadele": "Diel kľukového mechanizmu",
    "Ventily a ventilové sady": "Ventil alebo ventilová sada",
    "Rozvody": "Diel rozvodov motora",
    "Tesnenia motora": "Tesnenie motora",
    "Guferá": "Gufero alebo sada gufer",
    "Spojky a spojkové diely": "Spojkový diel",
    "Prevodovka": "Diel prevodovky",
    "Kryty motora": "Kryt motora",
    "Karburátory a diely karburátorov": "Diel karburátora",
    "Vstrekovanie paliva": "Diel vstrekovania paliva",
    "Palivové čerpadlá": "Palivové čerpadlo",
    "Palivové kohúty a nádrže": "Diel palivovej sústavy",
    "Chladiče": "Diel chladiča",
    "Vodné pumpy a opravné sady": "Diel vodnej pumpy",
    "Hadice a termostaty": "Hadica alebo termostat",
    "Štartéry a štartovacie relé": "Štartér alebo štartovacie relé",
    "Alternátory a regulátory": "Alternátor alebo regulátor napätia",
    "Zapaľovanie": "Diel zapaľovania",
    "Zapaľovacie sviečky a fajky": "Zapaľovacia sviečka alebo fajka",
    "Batérie": "Batéria",
    "Snímače a spínače": "Snímač alebo spínač",
    "Ovládače a vypínače": "Ovládač alebo vypínač",
    "Osvetlenie a smerovky": "Svetlo alebo smerovka",
    "Kabeláž, žiarovky a poistky": "Diel elektrickej sústavy",
    "Merače motohodín": "Merač motohodín",
    "Olejové filtre": "Olejový filter",
    "Vzduchové filtre": "Vzduchový filter",
    "Palivové filtre": "Palivový filter",
    "Motorové oleje 2T": "Motorový olej 2T",
    "Motorové oleje 4T": "Motorový olej 4T",
    "Vidlicové a tlmičové oleje": "Vidlicový a tlmičový olej",
    "Prevodové oleje": "Prevodový olej",
    "Hydraulické oleje": "Hydraulický olej",
    "Brzdové kvapaliny": "Brzdová kvapalina",
    "Chladiace kvapaliny": "Chladiaca kvapalina",
    "Mazivá a vazelíny": "Mazivo",
    "Servisná chémia a čističe": "Servisná chémia",
    "Výfuky": "Výfuk",
    "Koncovky výfukov": "Koncovka výfuku",
    "Zvody": "Výfukový zvod",
    "Tesnenia a príslušenstvo výfukov": "Tesnenie alebo príslušenstvo výfuku",
    "Sedadlá, peny a poťahy": "Diel sedadla",
    "Plexi a kapotáže": "Plexi alebo diel kapotáže",
    "Blatníky a bočné plasty": "Plast karosérie",
    "Kryty a chrániče motora": "Ochranný diel motora",
    "Zrkadlá": "Spätné zrkadlo",
    "Polepy a nálepky": "Polep alebo nálepka",
    "Plasty podľa značky motocykla": "Plast karosérie",
    "Variátorové remene": "Variátorový remeň",
    "Variátory a CVT": "Diel variátora CVT",
    "Diferenciály": "Diel diferenciálu",
    "Poloosy": "Poloos",
    "Kĺby a manžety": "Kĺb alebo manžeta poloosi",
    "Navijaky": "Navijak alebo diel navijaka",
    "Pluhy": "Pluh alebo diel pluhu",
    "Ťažné zariadenia": "Ťažné zariadenie",
}

COLORS = {
    "bialy": "biely", "biala": "biela", "biale": "biele",
    "czarny": "čierny", "czarna": "čierna", "czarne": "čierne",
    "czerwony": "červený", "czerwona": "červená", "czerwone": "červené",
    "niebieski": "modrý", "niebieska": "modrá", "niebieskie": "modré",
    "zielony": "zelený", "zielona": "zelená", "pomaranczowy": "oranžový",
    "zolty": "žltý", "zolta": "žltá", "zolte": "žlté",
    "zloty": "zlatý", "zlota": "zlatá", "srebrny": "strieborný",
}


def fold_polish(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.translate(str.maketrans({"ł": "l"}))


def variants(source_name: str) -> list[str]:
    folded = fold_polish(source_name)
    result = []
    for word, translated in COLORS.items():
        if re.search(rf"\b{word}\b", folded):
            result.append(translated)
            if len(result) == 2: break
    if re.search(r"\b(przod|przedni|predny)\b", folded): result.append("predný")
    if re.search(r"\b(tyl|tylny|zadny)\b", folded): result.append("zadný")
    if re.search(r"\b(lewy|lavy)\b", folded): result.append("ľavý")
    if re.search(r"\b(prawy|pravy)\b", folded): result.append("pravý")
    size = re.search(r"\b(?:rozmiar|velkost)\s+(\d{2,3}|[xsml]{1,3})\b", folded, re.I)
    if size: result.append("veľkosť " + size.group(1).upper())
    return list(dict.fromkeys(result))


def vehicle_brands(item: ET.Element) -> list[str]:
    result = []
    for node in item.findall("./CATEGORIES/CATEGORY"):
        path = (node.text or "").strip()
        match = re.search(r"Diely podľa (?:motocykla|ATV) > ([^>]+)", path)
        if match:
            brand = match.group(1).strip()
            if brand and brand not in result:
                result.append(brand)
    return result[:4]


def set_hidden(item: ET.Element) -> None:
    visibility = item.find("VISIBILITY")
    if visibility is None:
        visibility = ET.SubElement(item, "VISIBILITY")
    visibility.text = "hidden"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("selected_xml", type=Path)
    parser.add_argument("supplier_feed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    by_code, by_ean, _, _ = supplier_index(args.supplier_feed)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    counts: collections.Counter[str] = collections.Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as output, args.review.open("w", encoding="utf-8", newline="") as review:
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
        writer = csv.DictWriter(review, fieldnames=("code", "old_name", "supplier_name", "default_category", "problem"))
        writer.writeheader()
        for _, item in ET.iterparse(args.selected_xml, events=("end",)):
            if item.tag != "SHOPITEM": continue
            counts["products"] += 1
            old_name = (item.findtext("NAME") or "").strip()
            if not GENERIC.search(old_name):
                counts["non_generic_preserved"] += 1
            else:
                code = (item.findtext("CODE") or "").strip()
                ean = (item.findtext("EAN") or "").strip()
                cm, em = by_code.get(code), by_ean.get(ean) if ean else None
                conflict = bool(cm and em and cm["supplier_id"] != em["supplier_id"])
                source = None if conflict else cm or em
                category = (item.findtext("./CATEGORIES/DEFAULT_CATEGORY") or "").strip()
                leaf = category.rsplit(" > ", 1)[-1]
                type_name = TYPE_NAMES.get(leaf)
                if source and type_name and "Na ručnú kontrolu" not in category:
                    brand = (item.findtext("MANUFACTURER") or source["supplier_brand"] or "").strip()
                    parts = [type_name, brand, code]
                    suffix = vehicle_brands(item) + variants(source["supplier_name_pl"])
                    new_name = " ".join(x for x in parts if x)
                    if suffix: new_name += " – " + ", ".join(suffix)
                    item.find("NAME").text = new_name[:250]
                    counts["generic_renamed"] += 1
                else:
                    # Only feed-managed generics are hidden. Unmatched manual products stay untouched.
                    if source:
                        set_hidden(item)
                        counts["generic_hidden_for_review"] += 1
                    else:
                        counts["generic_manual_preserved"] += 1
                    writer.writerow({"code": code, "old_name": old_name, "supplier_name": source["supplier_name_pl"] if source else "", "default_category": category, "problem": "code_ean_conflict" if conflict else "missing_exact_type" if source else "manual_or_unmatched"})
            output.write(ET.tostring(item, encoding="utf-8", short_empty_elements=True)); output.write(b"\n"); item.clear()
        output.write(b"</SHOP>\n")
    ET.parse(temporary); temporary.replace(args.output)
    args.summary.write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
