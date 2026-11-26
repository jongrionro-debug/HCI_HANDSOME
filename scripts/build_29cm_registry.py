#!/usr/bin/env python3
"""29CM 수집 원문 PI를 고정 규칙으로 정규화한다(build_lumi_pi_v2.py가 resolve를 쓴다).

원래는 lumi-29cm-v1 실행 사전도 만들었으나 그 사전은 PI v3(lumi-pi-v3)로 대체되어 지웠다(#33).
남은 것은 축별 정규화 규칙(normalize)과 원문·모델 보완값에서 canonical 값을 고르는 resolve다.
"""

from __future__ import annotations

import re
from typing import Any

AXES = ("Type", "Brand", "Price", "Color", "Fit", "Fabric", "Detail")

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
    ("면", r"cotton|코튼|(?<![가-힣])면(?![가-힣])|면\s*\d|면스판"),
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
        types = TYPE_BY_GARMENT.get(garment, {})
        value = types.get(text.strip()) or (text.strip() if text.strip() in types.values() else None)
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
