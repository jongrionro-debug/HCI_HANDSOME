#!/usr/bin/env python3
"""29CM 수집 결과에서 PI value 사전(lumi-29cm-v1)과 완전 채움 상품 카탈로그를 만든다.

ADR 0010: PI 7개 축은 유지하고 value는 수집 데이터에서 정한다. 이 스크립트는
``fill_pi_deepseek.py export``가 만든 ``lumi-catalog-v1.jsonl``(원문 ``pi_raw``와
DeepSeek 보완 ``pi_model_interpretation`` 포함)을 읽어 다음을 수행한다.

1. 각 축의 원문/모델 값을 아래 고정 규칙으로 정규화한다. 규칙에 맞지 않는 값
   (예: "상세설명참조", 본문 조각, "DETAIL")은 채워지지 않은 것으로 본다.
2. 7개 축이 모두 정규화 value를 가진 상품만 남긴다.
3. 남은 상품의 value 분포로 사전 JSON을 만들고(Brand는 남은 상품의 브랜드 전체,
   Price는 고정 KRW 구간), 상품 레코드를 canonical value와 근거를 포함해 내보낸다.

공급 원문에서 정규화한 값은 ``raw_metadata.<축>``의 canonical 목록으로 두어 기존
매핑 경로가 exact metadata로 읽는다. DeepSeek 보완값은 ``labels``의
``status=inferred``·``model_interpretation``으로 두어 출처를 구분한다.

    python3 scripts/build_29cm_registry.py --catalog-dir ~/Documents/LUMI-data/29cm-catalog
    python3 scripts/build_29cm_registry.py --catalog-dir DIR --check   # 사전이 정본과 같은지
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PARK = ROOT / "output/feature-map/park-2025-feature-map.json"
REGISTRY = ROOT / "output/feature-map/lumi-29cm-v1.json"
VERSION = "lumi-29cm-v1"
AXES = ("Type", "Brand", "Price", "Color", "Fit", "Fabric", "Detail")
FIELD = {"Type": "type", "Brand": "brand", "Price": "price_range", "Color": "color",
         "Fit": "fit", "Fabric": "fabric", "Detail": "detail"}

GARMENT_LABELS = {
    "Pants": "바지", "Skirt": "스커트", "T-shirt": "티셔츠", "Shirt": "셔츠", "Blouse": "블라우스",
    "Knit/Sweater": "니트", "Sweatshirt": "스웨트셔츠", "Hoodie": "후디", "Polo": "폴로·카라 티셔츠",
    "Sleeveless": "슬리브리스",
}

# 29CM 소분류 → Type. 상위 분류만 있는 일반 이름(하의·기타 팬츠 등)은 값으로 쓰지 않는다.
TYPE_BY_GARMENT = {
    "Pants": {"코튼 팬츠": "코튼 팬츠", "부츠컷": "부츠컷 팬츠", "와이드": "와이드 팬츠", "와이드 팬츠": "와이드 팬츠",
              "쇼트": "쇼트 팬츠", "슬랙스": "슬랙스", "트레이닝": "트레이닝 팬츠", "트레이닝 팬츠": "트레이닝 팬츠",
              "레깅스": "레깅스", "슬림": "슬림 팬츠", "데님": "데님 팬츠", "데님 팬츠": "데님 팬츠",
              "스트레이트": "스트레이트 팬츠", "스트레이트 팬츠": "스트레이트 팬츠"},
    "Skirt": {"미디": "미디 스커트", "롱": "롱 스커트", "미니": "미니 스커트", "데님": "데님 스커트"},
    "Knit/Sweater": {"크루넥": "크루넥 니트", "브이넥": "브이넥 니트", "폴로셔츠": "폴로 니트", "터틀넥": "터틀넥 니트",
                     "집업": "집업 니트", "캐시미어": "캐시미어 니트", "후드": "후드 니트", "카디건": "카디건"},
    "T-shirt": {"반소매 티셔츠": "반소매 티셔츠", "긴소매 티셔츠": "긴소매 티셔츠", "아노락": "아노락", "플리스": "플리스"},
    "Shirt": {"반소매 셔츠": "반소매 셔츠", "긴소매 셔츠": "긴소매 셔츠", "셔츠": "셔츠"},
    "Sweatshirt": {"스웨트셔츠": "스웨트셔츠", "집업": "스웨트 집업"},
    "Hoodie": {"후디": "후디"},
    "Polo": {"피케/카라 티셔츠": "피케·카라 티셔츠"},
    "Sleeveless": {"슬리브리스": "슬리브리스"},
    "Blouse": {"블라우스": "블라우스"},
}

# 하한 포함·상한 미포함 KRW 구간.
PRICE_BUCKETS = ((0, 40000, "4만원 미만"), (40000, 60000, "4만~6만원"), (60000, 90000, "6만~9만원"),
                 (90000, 130000, "9만~13만원"), (130000, None, "13만원 이상"))

# (canonical, pattern). 앞쪽 규칙이 일치한 구간은 뒤 규칙에서 다시 쓰지 않는다.
COLOR_RULES = [
    ("스카이블루", r"light\s*blue|l\.\s*blue|sky\s*-?\s*blue|skyb|라이트\s*블루|베이비\s*블루|스카이\s*블루|\bsky\b|ash\s*blue|민트\s*블루|smoking\s*blue|storm|스톰\s*블루"),
    ("네이비", r"navy|네이비"),
    ("차콜", r"charcoal|챠콜|차콜|graphite|pewter|퓨터"),
    ("블랙", r"black|블랙|오닉스"),
    ("화이트", r"white|화이트"),
    ("아이보리", r"ivory|아이보리|cream|크림|ecru|에크루|custard|버터|oat\w*|오트밀"),
    ("베이지", r"beige|베이지|sand|stone|camel|카멜|듄|세피아"),
    ("브라운", r"brown|브라운|mocha|모카|d\.\s*brown|엠버|amber"),
    ("카키", r"khaki|카키|olive|올리브"),
    ("그린", r"green|그린|mint|민트|emerald|teal|청록|라임|lime"),
    ("블루", r"blue|블루|indigo|인디고|cpindigo|denim"),
    ("그레이", r"gr[ae]y|그레이|회색|melange|멜란지|silver|smoke|스모크"),
    ("레드", r"\bred\b|레드|burgundy|버건디|coral|마젠타|magenta"),
    ("핑크", r"pink|핑크"),
    ("퍼플", r"purple|퍼플|plum|라벤더|lavender|podo"),
    ("옐로우", r"yellow|옐로우|gold"),
    ("멀티", r"\bmulti\b|멀티"),
]
FIT_RULES = [
    ("세미오버", r"세미\s*-?\s*오버|semi[\s-]*over"),
    ("오버", r"오버|oversiz|\bover\s*fit"),
    ("와이드", r"와이드|wide|버뮤다|넓은"),
    ("부츠컷·플레어", r"부츠\s*컷|boot\s*-?\s*cut|flare|플레어"),
    ("슬림", r"슬림|slim|스키니|skinny|타이트|tight|snug|밀착|컴프레션|compression"),
    ("레귤러", r"레귤러|regular|스탠다드|standard"),
    ("루즈·릴랙스", r"루즈|loose|relax|릴랙스|릴렉스|여유|넉넉|boxy|풍성|볼륨|balloon"),
    ("스트레이트", r"스트레이트|straight|일자"),
    ("A라인", r"a\s*-?\s*line|a라인"),
    ("H라인", r"h\s*-?\s*line|h라인"),
    ("크롭", r"크롭|crop|capri|7부"),
    ("조거", r"조거|jogger"),
]
FABRIC_RULES = [
    ("캐시미어", r"cashmere|캐시미어"),
    ("울", r"wool|울(?!트라)|merino|메리노|모\s*\d"),
    ("면", r"cotton|코튼|면\s*\d|%\s*면|면스판"),
    ("폴리에스터", r"polyester|폴리에스터|폴리에스테르|poly(?!u|amide|ure)\w*|폴리(?!우레탄|아미드)"),
    ("나일론", r"nylon|나일론|polyamide|폴리아미드"),
    ("폴리우레탄", r"polyure\w*|폴리우레탄|spandex|\bspan\b|스판|elastane|엘라스탄|\bpu\b"),
    ("레이온", r"rayon|레이온|viscose|비스코스"),
    ("아크릴", r"acrylic|아크릴"),
    ("린넨", r"linen|린넨|리넨|마\s*\d"),
    ("실크", r"silk|실크"),
    ("리오셀", r"lyocell|리오셀|tencel|텐셀"),
    ("모달", r"modal|모달"),
    ("알파카", r"alpaca|알파카"),
    ("모헤어", r"mohair|모헤어"),
    ("아세테이트", r"acetate|아세테이트"),
]
DETAIL_RULES = [
    ("하프집업", r"하프\s*집업|반\s*집업|half\s*zip|quarter\s*zip|1/2"),
    ("지퍼·집업", r"지퍼|집업|zip|ykk"),
    ("밴딩", r"밴딩|banding|elastic|엘라스틱|허리\s*밴드|waistband|허리밴드|드로인"),
    ("스트링", r"스트링|string|drawcord|조임끈|드로우|stopper|스토퍼"),
    ("턱·핀턱", r"(?<![가-힣])[원투]\s*턱|핀턱|pintuck|사이드\s*투턱|턱\("),
    ("플리츠·주름", r"플리츠|pleat|주름|셔링|shirring|smock|스모킹|wrinkle"),
    ("포켓", r"포켓|pocket|5pk"),
    ("버튼", r"버튼|단추|button|스냅|snap|후크|breasted"),
    ("슬릿·트임", r"슬릿|slit|트임"),
    ("워싱", r"워싱|wash|탈색"),
    ("리브·골지", r"리브|(?<![가-힣])립(?![가-힣]*스틱)|ribbed|\brib\b|골지|시보리"),
    ("카라", r"카라|칼라|collar"),
    ("후드", r"후드|hood|balaclava"),
    ("넥라인", r"브이넥|v\s*-?\s*neck|크루넥|라운드\s*넥|라운드넥|crew\s*neck|터틀넥|모크넥|mock\s*neck|헨리넥|하이넥|high\s*-?\s*neck|카울넥|유넥|넥라인|neckline"),
    ("로고·자수", r"로고|logo|자수|embroider|레터링|위드마크|라벨"),
    ("스트라이프", r"스트라이프|stripe"),
    ("체크·패턴", r"체크|check|아가일|argyle|패턴|pattern|print|프린트|그래픽|graphic"),
    ("레이스", r"레이스|lace"),
    ("벨트", r"벨트|belt|버클|buckle|웨빙"),
    ("기모", r"기모|brushed|fleece|플리스"),
    ("스티치", r"스티치|stitch"),
    ("타이", r"(?<![가-힣])타이(?!트|즈|츠)|\btie\b"),
    ("코듀로이", r"코듀로이|corduroy"),
]


def _match(text: str, rules: list[tuple[str, str]]) -> list[str]:
    text = text.casefold()
    found = []
    for canonical, pattern in rules:
        hits = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if hits:
            found.append(canonical)
            for hit in reversed(hits):  # 같은 구간이 뒤 규칙에서 다시 일치하지 않게 한다.
                text = text[:hit.start()] + " " * (hit.end() - hit.start()) + text[hit.end():]
    return found


def price_bucket(amount: int) -> str:
    for low, high, label in PRICE_BUCKETS:
        if amount >= low and (high is None or amount < high):
            return label
    raise ValueError(amount)


def normalize(feature: str, text: str, garment: str) -> list[str]:
    if feature == "Type":
        value = TYPE_BY_GARMENT.get(garment, {}).get(text.strip())
        return [value] if value else []
    if feature == "Brand":
        return [text.strip()] if text.strip() else []
    rules = {"Color": COLOR_RULES, "Fit": FIT_RULES, "Fabric": FABRIC_RULES, "Detail": DETAIL_RULES}[feature]
    return _match(text, rules)


def resolve(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """축별 canonical 값과 출처(raw|model). 값이 없으면 그 축은 빠진다."""
    raw_md = record["raw_metadata"]
    garment = record["garment_type"]
    result = {}
    for feature in AXES:
        raw = raw_md["pi_raw"].get(feature) or {}
        if feature == "Price":
            if isinstance(raw_md.get("price"), int) and raw_md.get("currency") == "KRW":
                result[feature] = {"values": [price_bucket(raw_md["price"])], "origin": "raw",
                                   "quote": str(raw_md["price"])}
            continue
        if raw.get("source") not in (None, "none", "referred") and isinstance(raw.get("value"), str):
            values = normalize(feature, raw["value"], garment)
            if values:
                result[feature] = {"values": values, "origin": "raw", "quote": raw["value"]}
                continue
        model = (raw_md.get("pi_model_interpretation") or {}).get(feature)
        if model and isinstance(model.get("value"), str):
            values = normalize(feature, model["value"], garment)
            if values:
                result[feature] = {"values": values, "origin": "model", "quote": model["value"]}
    return result


def export_record(record: dict[str, Any], resolved: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_md = deepcopy(record["raw_metadata"])
    # 원문 문자열 필드를 canonical 축 필드와 겹치지 않는 이름으로 옮긴다.
    for old, new in (("brand", "brand_text"), ("price", "price_amount"), ("color", "color_text"),
                     ("fabric", "fabric_text")):
        if old in raw_md:
            raw_md[new] = raw_md.pop(old)
    labels = []
    for feature in AXES:
        entry = resolved[feature]
        if entry["origin"] == "raw":
            raw_md[FIELD[feature]] = entry["values"]
        else:
            labels.append({
                "observation": {"domain": "PI", "feature": feature, "values": entry["values"]},
                "status": "inferred",
                "provenance": [{"kind": "model_interpretation",
                                "source_field": f"raw_metadata.pi_model_interpretation.{feature}.value",
                                "quote": entry["quote"], "verifier": None, "evidence_ref": None,
                                "verified_at": None}],
            })
    raw_md["lumi_normalization"] = {"registry_version": VERSION,
                                    "origin": {f: resolved[f]["origin"] for f in AXES}}
    result = deepcopy(record)
    result["raw_metadata"] = raw_md
    result["labels"] = labels
    return result


def build_registry(complete: list[tuple[dict[str, Any], dict[str, dict[str, Any]]]]) -> dict[str, Any]:
    park = json.loads(PARK.read_text(encoding="utf-8"))
    counts: dict[str, Counter] = {feature: Counter() for feature in AXES}
    types: dict[str, set[str]] = {}
    for record, resolved in complete:
        for feature in AXES:
            counts[feature].update(resolved[feature]["values"])
        types.setdefault(record["garment_type"], set()).update(resolved["Type"]["values"])

    def ordered(feature: str) -> list[str]:
        if feature == "Price":
            return [label for _, _, label in PRICE_BUCKETS]
        if feature == "Brand":
            return sorted(counts[feature])
        rules = {"Color": COLOR_RULES, "Fit": FIT_RULES, "Fabric": FABRIC_RULES, "Detail": DETAIL_RULES}.get(feature)
        if rules:
            return [c for c, _ in rules if c in counts[feature]]
        return sorted(counts[feature])

    labels = {"Type": "아이템 종류", "Brand": "브랜드", "Price": "가격 구간", "Color": "색상", "Fit": "핏",
              "Fabric": "소재 원료", "Detail": "디테일"}
    pi = {}
    for feature in AXES:
        values = ordered(feature)
        pi[feature] = {"label_ko": labels[feature], "values": values, "reported_count": len(values),
                       "enumeration_complete": True,
                       "distribution": {v: counts[feature][v] for v in values}}
    pi["Type"]["values_by_garment_type"] = {g: sorted(v) for g, v in sorted(types.items())}
    pi["Price"]["currency"] = "KRW"
    pi["Price"]["boundaries"] = [{"label": label, "min_inclusive": low, "max_exclusive": high}
                                 for low, high, label in PRICE_BUCKETS]
    garments = sorted(types)
    return {
        "name": "LUMI 29CM collected PI values + Park FEA taxonomy",
        "version": VERSION,
        "status": "Generated",
        "runtime_implemented": True,
        "scope": "29CM 상·하의 수집 상품 중 PI 7개 축이 모두 정규화된 상품에서 만든 value 사전이다.",
        "lumi_use": "ADR 0010에 따라 PI 축은 Park et al. (2025)를 유지하고 value만 수집 데이터에서 정한다. FEA 30개 태그는 Park 사전을 그대로 쓴다.",
        "generated_by": "scripts/build_29cm_registry.py",
        "product_information": pi,
        "consumer_needs_taxonomy": park["consumer_needs_taxonomy"],
        "garment_types": [{"value": g, "label_ko": GARMENT_LABELS.get(g, g)} for g in garments],
        "execution": {
            "supported_garment_types": garments,
            "accept_inferred_product_pi": True,
            "price_currency": "KRW",
            "price_boundary_inclusion": "min_inclusive_max_exclusive",
        },
        "counts": {"products": len(complete), "product_information_categories": len(pi),
                   "consumer_needs_attributes": park["counts"]["consumer_needs_attributes"],
                   "values": {f: len(pi[f]["values"]) for f in AXES}},
        "source_boundaries": [
            "Type은 29CM 소분류, Brand는 표시 브랜드, Price는 판매가의 고정 KRW 구간이다.",
            "Color·Fit·Fabric·Detail은 원문 또는 DeepSeek 보완 문장에서 이 스크립트의 고정 키워드 규칙으로 찾은 값이다. 규칙에 없는 표현은 값으로 만들지 않는다.",
            "DeepSeek 보완값은 상품 Map에서 status=inferred·model_interpretation으로 남는다. accept_inferred_product_pi=true는 이 사전 버전에서 그 값을 상품 비교에 쓰도록 한 실행 선택이며 검증 라벨이 아니다.",
            "FEA 성능 태그를 상품 사진·문구만으로 확정하지 않는다.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog-dir", required=True, type=Path)
    parser.add_argument("--input", default="lumi-catalog-v1.jsonl")
    parser.add_argument("--output", default="lumi-catalog-complete-v1.jsonl")
    parser.add_argument("--report", default="complete_report.json")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--check", action="store_true", help="사전 파일을 쓰지 않고 정본과 같은지 확인")
    args = parser.parse_args()
    directory = args.catalog_dir.expanduser()
    if ROOT in directory.resolve().parents or directory.resolve() == ROOT:
        print("FAIL: 수집 데이터 경로는 저장소 밖이어야 합니다.", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in (directory / args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    complete, missing = [], Counter()
    for record in records:
        resolved = resolve(record)
        absent = [f for f in AXES if f not in resolved]
        missing.update(absent)
        if not absent:
            complete.append((record, resolved))
    registry = build_registry(complete)
    text = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not args.registry.is_file() or args.registry.read_text(encoding="utf-8") != text:
            print(f"FAIL: {args.registry}가 현재 데이터로 만든 사전과 다릅니다.")
            return 1
        print("OK: registry matches collected data")
        return 0
    args.registry.write_text(text, encoding="utf-8")
    out = directory / args.output
    out.write_text("".join(json.dumps(export_record(r, v), ensure_ascii=False) + "\n" for r, v in complete),
                   encoding="utf-8")
    origin = Counter((f, v[f]["origin"]) for _, v in complete for f in AXES)
    report = {
        "registry_version": VERSION, "input_records": len(records), "complete_records": len(complete),
        "by_group": dict(Counter(r["raw_metadata"]["group"] for r, _ in complete)),
        "by_garment_type": dict(Counter(r["garment_type"] for r, _ in complete)),
        "missing_by_axis": {f: missing[f] for f in AXES},
        "origin_by_axis": {f: {"raw": origin[(f, "raw")], "model": origin[(f, "model")]} for f in AXES},
        "value_counts": registry["counts"]["values"],
    }
    (directory / args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
