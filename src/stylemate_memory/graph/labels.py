"""Korean display labels for PI v2/v3 values (UI U1). Display only: stored values stay as in the registry.

A value without an entry is shown as stored. The registry (lumi-pi-v5.1) remains the
source of truth for which values exist; this table never adds or renames a value.
"""

from __future__ import annotations

VALUE_LABELS_KO: dict[str, dict[str, str]] = {
    "Type": {"T-shirt": "반소매 티셔츠", "Long-sleeve T-shirt": "긴소매 티셔츠", "Polo": "폴로·카라 티셔츠", "Shirt": "셔츠",
             "Overshirt": "오버셔츠", "Blouse": "블라우스", "Sweater": "스웨터·니트", "Cardigan": "카디건",
             "Knit vest": "니트 베스트", "Sleeveless": "민소매", "Sweatshirt": "스웨트셔츠", "Hoodie": "후디",
             "Zip hoodie": "후드 집업", "Trousers": "바지", "Jeans": "청바지", "Sweatpants": "트레이닝 팬츠",
             "Cargo pants": "카고 팬츠", "Shorts": "반바지", "Skirt": "스커트", "Leggings": "레깅스", "Skort": "스커트 팬츠",
             "Field jacket": "필드 재킷", "Blouson": "블루종", "Varsity jacket": "바시티 재킷", "Denim jacket": "데님 재킷",
             "Fur jacket": "퍼 재킷", "Track jacket": "트랙 재킷", "Jumper": "점퍼", "Windbreaker": "바람막이",
             "Anorak": "아노락", "Fleece jacket": "플리스 재킷", "Shearling jacket": "무스탕", "Trench coat": "트렌치코트",
             "Coach jacket": "코치 재킷", "Vest": "베스트·조끼", "Leather jacket": "가죽 재킷", "Blazer": "블레이저",
             "Coat": "코트", "Padded jacket": "패딩", "Nylon jacket": "나일론 재킷", "Raincoat": "레인코트",
             "Robe": "로브", "Jacket": "재킷"},
    "Color": {"Black": "검정", "White": "흰색", "Ecru": "에크루", "Grey": "회색", "Charcoal": "차콜", "Navy": "네이비",
              "Blue": "파랑", "Light blue": "하늘색", "Brown": "갈색", "Beige": "베이지", "Khaki": "카키", "Green": "초록",
              "Red": "빨강", "Pink": "분홍", "Purple": "보라", "Yellow": "노랑", "Orange": "주황", "Multi": "여러 색"},
    "Tone": {"Dark": "어두운 톤", "Medium": "중간 톤", "Light": "밝은 톤"},
    "Pattern": {"Solid": "무지", "Stripe": "스트라이프", "Check": "체크", "Graphic": "그래픽", "Logo": "로고",
                "Floral": "꽃무늬", "Jacquard": "자카드", "Other": "기타 무늬", "Dot": "도트"},
    "Fit": {"Slim": "슬림 핏", "Regular": "레귤러 핏", "Relaxed": "여유 핏", "Oversized": "오버핏"},
    "Silhouette": {"Straight": "스트레이트", "Tapered": "테이퍼드", "Wide": "와이드", "Flare": "플레어", "Boxy": "박시",
                   "Pencil": "펜슬", "H-line": "H라인", "A-line": "A라인", "Mermaid": "머메이드"},
    "Length": {"Short sleeve": "반소매", "Long sleeve": "긴소매", "Sleeveless": "민소매", "Cropped": "크롭",
               "Shorts": "짧은 기장", "Full": "긴 기장", "Short": "짧은 기장", "Hip": "엉덩이 기장",
               "Half": "하프 기장", "Long": "롱 기장", "Mini": "미니", "Knee": "무릎 기장", "Midi": "미디"},
    "Texture": {"Jersey": "저지", "Knit": "니트", "Ribbed": "골지", "Fleece": "플리스", "Denim": "데님",
                "Corduroy": "코듀로이", "Twill": "트윌", "Seersucker": "시어서커", "Waffle": "와플", "Boucle": "부클",
                "Smooth": "매끈한 표면", "Suede": "스웨이드", "Quilted": "퀼팅", "Shearling": "시어링",
                "Melton": "멜톤", "Ripstop": "립스톱", "Tweed": "트위드", "Velvet": "벨벳", "Lace": "레이스", "Satin": "새틴",
                "Tulle": "튤", "Fuzzy": "보송한 표면", "Glossy": "광택", "Matte": "무광", "Crinkled": "구김 주름",
                "Grained": "그레인 가죽", "Mesh": "메시", "Herringbone": "헤링본", "Cable knit": "꽈배기 니트",
                "Open knit": "성긴 니트"},
    "Fabric": {"Cotton": "면", "Wool": "울", "Cashmere": "캐시미어", "Linen": "린넨", "Polyester": "폴리에스터",
               "Nylon": "나일론", "Viscose": "비스코스", "Elastane": "스판", "Acrylic": "아크릴", "Silk": "실크",
               "Leather": "가죽", "Fur": "퍼", "Down": "다운", "Alpaca": "알파카", "Mohair": "모헤어", "Angora": "앙고라"},
    "Detail": {"Pockets": "포켓", "Zip": "지퍼", "Buttons": "단추", "Collar": "칼라", "Hood": "후드", "Drawcord": "스트링",
               "Elastic waist": "밴딩 허리", "Pleats": "주름", "Embroidery": "자수", "Patch": "패치", "Washed": "워싱",
               "Distressed": "디스트레스드", "Slit": "트임", "Wrap": "랩",
               "Tiered": "티어드", "Ruffle": "러플", "Hook fastening": "후크 여밈", "Reversible": "리버서블"},
    "Style": {"Vintage": "빈티지", "Sporty": "스포티", "Workwear": "워크웨어", "Tailored": "테일러드", "Classic": "클래식",
              "Preppy": "프레피", "Street": "스트리트", "Minimal": "미니멀", "Casual": "캐주얼", "Formal": "포멀",
              "Outdoor": "아웃도어", "Feminine": "페미닌"},
    "Weight": {"Light": "얇은 두께", "Mid": "중간 두께", "Heavy": "두꺼운 두께"},
}


def value_label(axis: str, value: str) -> str:
    return VALUE_LABELS_KO.get(axis, {}).get(value, value)
