# 0018 · PI v4: 남성 아우터 품목군을 더한다

- Status: Proposed
- Date: 2026-11-24
- Related Work: 현재 요청(29CM 남성 아우터 1,000개 수집과 PI 확장)
- Approval: 2026-11-24 사용자 결정(팀 회의)
  - Type·Length·Fabric·Texture를 확정해 추가한다
  - Silhouette은 아우터에서 쓰지 않는다
  - 후드 집업은 아우터에서 별도 Type으로 둔다
  - 소분류에서 고르게 뽑고 베스트·후드 집업을 포함한다
  - 이 ADR의 Accepted 승인은 미승인이다
- Supersedes: [ADR 0016](0016-pi-v3-value-shapes.md)을 대체하지 않고 확장한다. v3의 상의·하의 규칙과 결과물은 그대로 둔다. v3 결정 5의 Type 병합 중 `Zip hoodie→Hoodie`는 v4에서 상의에만 적용한다.

## 맥락

29CM 남성의류 > 아우터(상품 37,687개, 소분류 24개)에서 1,000개를 수집한다. PI v3는 상의·하의만 다룬다.

- Type에 아우터 값이 없다.
- Length 점수는 상의 소매와 하의 기장뿐이라 아우터 기장(숏·하프·롱)을 담지 못한다.
- Weight 품목 규칙이 상의·하의 기준이라 패딩·코트를 구분하지 못한다.
- Fabric·Texture에 가죽, 퍼, 스웨이드, 퀼팅, 무스탕, 멜톤 같은 아우터 소재가 없다.

## 결정

정본은 [build_lumi_pi_v4.py](../../scripts/build_lumi_pi_v4.py)의 `SCHEMA`와 `outer_*` 함수다. 모델은 호출하지 않는다.

1. **품목군 `outer`를 더한다.** Fit·Length 점수는 품목군마다 따로 매기고 서로 비교하지 않는다(v3 원칙 유지).
2. **Type(범주형, 필터).** 29CM 소분류에서 하나씩 정한다(`confirmed`, `subcategory`). 코트와 패딩은 Type 하나로 묶고 기장은 Length로 나눈다.

    | 소분류 | Type |
    |---|---|
    | 야상 · 블루종 · 바시티 · 데님 재킷 | Field jacket · Blouson · Varsity jacket · Denim jacket |
    | 퍼 재킷 · 트레이닝 재킷 · 점퍼 · 바람막이 | Fur jacket · Track jacket · Jumper · Windbreaker |
    | 아노락 · 플리스 · 무스탕 · 트렌치/맥코트 | Anorak · Fleece jacket · Shearling jacket · Trench coat |
    | 나일론/코치 재킷 · 후드 집업 · 베스트 | Coach jacket · Zip hoodie · Vest |
    | 레더 재킷 · 블레이저 | Leather jacket · Blazer |
    | 숏코트 · 하프코트 · 롱코트 | Coat |
    | 경량패딩 · 숏패딩 · 롱패딩 | Padded jacket |
    | 기타 아우터 | 비워 두고 2순위(모델) 단계에서 채운다 |

    - v3의 Type 병합은 품목군별로 나눈다. 상의 `Knit vest→Sleeveless`·`Zip hoodie→Hoodie`, 하의 `Cargo pants→Trousers`, 아우터는 병합하지 않는다.
3. **Length(순서형).** 아우터는 몸판 기장으로 점수를 매긴다. Cropped 1, Short 2, Hip 3, Half 4, Long 5. 앞 단계가 정하면 뒤 단계는 보지 않는다.
    - (1) 소분류: 숏코트·숏패딩 Short, 하프코트 Half, 롱코트·롱패딩 Long (`confirmed`)
    - (2) 상품명·판매자 문구 키워드: 크롭·숏·하프·롱. 값이 둘 이상 걸리면 다음 단계로 넘긴다. 하프집업과 롱슬리브는 기장으로 보지 않는다 (`confirmed`)
    - (3) 실측표 총길이: M 열, 없으면 가운데 열. 55cm 미만 Cropped, 68 미만 Short, 80 미만 Hip, 95 미만 Half, 그 이상 Long (`confirmed`). 경계값은 가정이며 수집 분포를 보고 조정한다.
    - (4) Type 규칙: 블루종·바시티·점퍼·트레이닝·코치·바람막이·아노락·플리스·후드 집업·베스트·패딩은 Short. 데님·레더·블레이저·야상·무스탕·퍼는 Hip. 트렌치는 Long, 코트는 Half (`derived`)
4. **Weight(순서형, Light 1·Mid 2·Heavy 3).** v3 순서를 따르고 아우터 규칙을 더한다.
    - (1) GSM(200 미만 Light, 320 이상 Heavy)
    - (2) 두께·충전재 키워드: v3 키워드에 덕다운·구스다운·웰론·충전재·패딩·헤비·기모(Heavy)와 경량·메쉬·packable(Light)을 더한다. 값이 둘 이상이면 다음 단계로 넘긴다
    - (3) 소재 규칙: Shearling·Melton 표면감이나 Fur 소재는 Heavy, 울·캐시미어 코트는 Heavy, Ripstop은 Light
    - (4) 소분류·Type 규칙: 경량패딩은 Mid. 패딩·코트·무스탕·퍼는 Heavy. 바람막이·아노락·코치·트레이닝·베스트는 Light. 나머지는 Mid
    - (1)(2)는 `confirmed`, (3)(4)는 `derived`다.
5. **Fabric·Texture 값을 더한다.**
    - Fabric: Leather, Fur. 충전재는 겉감이 아니므로 Fabric에 넣지 않고 Weight 근거로만 쓴다.
    - Texture: Suede, Quilted, Shearling, Melton, Ripstop, Tweed
    - 판매자 문구 키워드가 있으면 `confirmed`다. 없으면 소분류로 정한다(`derived`): 레더 재킷 Leather, 퍼 재킷 Fur, 무스탕 Shearling, 플리스 Fleece, 데님 재킷 Denim.
    - "퍼"만으로는 Fur로 보지 않는다(퍼플·슈퍼와 겹친다). 페이크퍼·퍼 카라처럼 앞뒤 말이 있어야 한다.
6. **나머지 축은 v3 그대로다.** Color·Tone(대표색, 29CM 모델 컷은 상의와 같은 위쪽 띠), Fit, Pattern, Detail, Style, Price, Brand를 v2·v3 함수로 채운다. Silhouette은 아우터에서 쓰지 않는다.
7. **드문 값 병합(v3 결정 5)은 아우터에 아직 적용하지 않는다.** 1,000개 분포를 본 뒤 정한다.

## 대안

- **소분류 24개를 모두 Type으로:** 숏·하프·롱코트와 경량·숏·롱패딩이 Type과 Length 두 축에 같은 정보를 담는다.
- **아우터 Length를 상의 소매 점수에 섞기:** 아우터는 거의 모두 긴소매라 구분력이 없다.
- **충전재 축 신설:** 이번 결정 범위 밖이다. 다운·충전재는 Weight 키워드로만 쓴다.
- **v3 파일을 직접 고치기:** 이미 만든 1,748개 결과의 재현 계약을 바꾼다. v4가 v3를 불러 쓰고 아우터만 더한다.

## 영향

- `build_lumi_pi_v4.py --schema`가 v4 스키마를 JSON으로 출력한다. `outer_pi`가 상품 하나의 Type·Length·Weight·Fabric·Texture를 규칙으로 채운다. 단위 테스트는 [test_pi_v4.py](../../tests/test_pi_v4.py)다.
- 아직 실제 아우터 데이터로 빌드하지 않았다. 수집기의 아우터 시드와 CSV 내보내기는 후속 작업이다.
- **위험:**
    - Length 실측 경계값은 가정이다.
    - "점퍼" 소분류는 범위가 넓어 Type이 모호할 수 있다.
    - Weight를 Type 규칙만으로 채운 상품이 많을 수 있다. 채움 경로별 개수를 보고한다.
- **후속 작업:**
    - 수집 후 축별 채움률과 총길이 분포를 기록하고 경계값을 정한다.
    - 2순위 모델 라벨링과 충돌 표시를 한다.
    - 실행 사전 내보내기와 graph 엔진 연결은 별도 작업이다.
