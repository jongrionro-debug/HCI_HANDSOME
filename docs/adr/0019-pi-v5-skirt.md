# 0019 · PI v5: 스커트 품목군을 더한다

- Status: Proposed
- Date: 2026-11-26
- Related Work: 현재 요청(29CM 여성 스커트 800개 수집과 PI 확장)
- Approval: 2026-11-26 사용자 요청(스커트만 추가하고 원피스는 넣지 않는다). 팀 승인과 이 ADR의 Accepted 승인은 미승인이다
- Supersedes: [ADR 0018](0018-pi-v4-outer.md)을 대체하지 않고 확장한다. v4의 상의·하의·아우터 규칙과 결과물은 그대로 둔다. v5에서는 `Skirt`가 하의 Type에서 빠져 스커트 품목군의 Type이 된다.

## 맥락

29CM 여성의류 > 스커트(중분류 268107100, 소분류 미니·미디·롱·데님)에서 800개를 수집한다. 20개 시험 수집에서 PI v3·v4로는 스커트를 담지 못하는 점이 보였다.

- Length의 하의 점수(Shorts·Cropped·Full)는 바지 기장이다. 스커트 기장(미니·무릎·미디·롱)이 들어갈 자리가 없다.
- Silhouette 값(Straight·Tapered·Wide·Flare)은 바지 통이다. 펜슬·H라인·A라인·머메이드가 없다.
- Fit(Slim~Oversized)은 스커트에서 Silhouette과 겹친다.
- 벨벳·레이스·새틴·튤 같은 표면감, 랩·티어드·러플 디테일, 도트 무늬가 없다.
- 소분류만으로는 모자라다.
    - 미디 소분류 상품 제목이 "Long Skirt"인 경우가 있다.
    - 데님 소분류에는 기장 정보가 없고, 울·펜슬 스커트도 섞여 있다.

## 결정

정본은 [build_lumi_pi_v5.py](../../scripts/build_lumi_pi_v5.py)의 `SCHEMA`와 `skirt_*` 함수다. 모델은 호출하지 않는다. 원피스는 이번 결정에 넣지 않는다.

1. **품목군 `skirt`를 더한다.** 점수는 품목군마다 따로 매기고 서로 비교하지 않는다(v3 원칙 유지).
2. **Type(범주형, 필터).** 스커트 품목군 값은 Skirt와 Skort다.
    - skort·skirt pants·큐롯·치마바지 키워드가 있으면 Skort(`confirmed`, `keyword`)다.
    - 그 밖에 소분류가 미니·미디·롱·데님이면 Skirt(`confirmed`, `subcategory`)다.
    - 하의 Type에서 Skirt를 뺀다. 하의 그리드에 바지와 스커트가 섞이지 않는다.
3. **Length(순서형).** 밑단 기장으로 점수를 매긴다. Mini 1, Knee 2, Midi 3, Long 4. 앞 단계가 정하면 뒤 단계는 보지 않는다.
    - (1) 상품명 키워드: 미니·무릎·미디·롱/맥시. 값이 둘 이상이면 다음 단계로 넘긴다. 미니멀과 롱슬리브는 기장으로 보지 않는다 (`confirmed`)
    - (2) 소분류: 미니 Mini, 미디 Midi, 롱 Long. 데님은 기장이 없다 (`confirmed`)
    - (3) 판매자 문구 키워드: (1)과 같은 규칙이다. 판매자 문구는 "미니 립 포켓"처럼 기장이 아닌 곳에도 같은 말을 써서 소분류 뒤에 둔다 (`confirmed`)
    - (4) 실측표 총장: M 열, 없으면 가운데 열. 45cm 미만 Mini, 62 미만 Knee, 82 미만 Midi, 그 이상 Long (`confirmed`). 경계값은 가정이며 수집 분포를 보고 조정한다.
    - 아무것도 없으면 비워 두고 2순위(모델) 단계에서 채운다.
4. **Silhouette(범주형).** 스커트 값은 Pencil, H-line, A-line, Flare, Mermaid다. 키워드가 하나만 걸리면 `confirmed`이고, 둘 이상이거나 없으면 비운다. Silhouette은 하의와 스커트가 쓰고 값 목록은 품목군별로 둔다.
5. **Fit은 스커트에서 쓰지 않는다.** 스커트의 핏은 Silhouette이 담는다.
6. **값을 더한다.** 판매자 문구 키워드가 있을 때만 채운다(`confirmed`).
    - Texture: Velvet, Lace, Satin, Tulle. 레이스업은 Lace, 튤립은 Tulle로 보지 않는다.
    - Detail: Wrap, Tiered, Ruffle. "랩"은 랩 스커트처럼 앞뒤 말이 있어야 한다(스트랩과 겹친다).
    - Pattern: Dot
    - Style: Feminine. 스커트 품목군에만 둔다.
    - 데님 소분류만으로 Texture를 Denim으로 정하지 않는다. 데님 키워드가 있어야 한다.
7. **Weight(순서형, Light 1·Mid 2·Heavy 3).** v3 순서를 따르고 스커트 규칙을 더한다.
    - (1) GSM, (2) v3 두께 키워드(값이 둘 이상이면 다음 단계로 넘긴다)는 `confirmed`다.
    - (3) 소재 규칙(`derived`)
        - Heavy: Velvet·Corduroy·Tweed·Melton·Suede·Boucle 표면감, Leather·Fur 소재, 상품명에 울·캐시미어
        - Light: Tulle·Lace·Seersucker 표면감, Linen 소재, 시폰·보일·오간자 키워드
        - 울은 상품명에 있을 때만 본다. 판매자 혼용률에는 폴리에스터 스커트에 울 4%처럼 적게 섞인 경우가 있다.
    - (4) 나머지는 Mid(`derived`, `type_rule`)
8. **나머지 축은 v3 그대로다.** Color·Tone(대표색, 29CM 모델 컷은 하의와 같은 아래쪽 띠), Pattern, Fabric, Detail, Style, Price, Brand를 v2·v3 함수로 채운다.

## 대안

- **스커트를 하의 품목군에 두고 Length 값만 더하기:** 하의 Length 점수에 바지 기장과 스커트 기장이 섞인다. 기장 1.0 차이의 뜻이 품목마다 달라진다.
- **소분류를 Length 1순위로:** 시험 수집에서 미디 소분류의 롱 스커트가 Midi로 잘못 들어간다.
- **Fit을 스커트에도 쓰기:** Silhouette과 같은 정보를 두 축에 담는다.
- **원피스를 함께 넣기:** 상의·하의 어느 쪽에도 맞지 않아 별도 결정이 필요하다. 이번 범위 밖이다.

## 영향

- `build_lumi_pi_v5.py --schema`가 v5 스키마를 JSON으로 출력한다.
- `skirt_pi`가 상품 하나의 Type·Length·Silhouette·Fabric·Texture·Detail·Pattern·Weight를 규칙으로 채운다.
- 단위 테스트는 [test_pi_v5.py](../../tests/test_pi_v5.py)다.
- 시험 수집 20개에 돌린 결과다.
    - Type·Weight는 20개 모두 채웠다.
    - Length는 18개를 채웠다. 남은 2개는 데님 소분류다.
    - Silhouette은 7개를 채웠다.
- 아직 800개 전체로 빌드하지 않았다.
- **위험:**
    - Length 실측 경계값은 가정이다.
    - Weight를 Mid 기본값으로 채운 상품이 많을 수 있다. 채움 경로별 개수를 보고한다.
    - Silhouette은 키워드가 없으면 비어 2순위 단계 부담이 크다.
- **후속 작업:**
    - 수집 후 축별 채움률과 총장 분포를 기록하고 경계값을 정한다.
    - 2순위 모델 라벨링과 충돌 표시를 한다.
    - 실행 사전 내보내기와 graph 엔진 연결은 별도 작업이다.
