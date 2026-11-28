# 0021 · 통합 PI map v5.1을 실행 사전과 카탈로그로 쓴다

- Status: Proposed
- Date: 2026-11-28
- Related Work: 2026-11-28 사용자 요청(최종 PI map·데이터 연결), 후속 [#41](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/41)
- Approval: 미승인. 사용자 요청으로 실행 경로에 연결했다. 파일럿 전 팀 확인 대상
- Supersedes: [ADR 0016](0016-pi-v3-value-shapes.md)의 실행 사전 `lumi-pi-v3`을 기본값에서 내린다(선택 가능으로 유지). 0016의 값 형태(점수·Lab·`price_krw`), [ADR 0018](0018-pi-v4-outer.md)·[ADR 0019](0019-pi-v5-skirt.md)의 품목군 정의는 그대로다

## 맥락

29CM 상의·하의·아우터·스커트 9,202개를 PI v5 스키마(+v4.3 확장 값)로 합친 통합 map(`lumi-pi-v5.1`, `data/catalog/lumi-pi-unified.jsonl`)이 나왔다. 실행 경로는 상·하의만 담은 `lumi-pi-v3` 사전과 그 가져오기 형식만 읽었고, 질문 루프([ADR 0020](0020-question-loop-v1.md))의 기장 점수는 상·하의 값만 아는 한 표였다. v5.1에서는 같은 기장 이름이 품목군마다 다른 점수를 갖는다(Cropped: 하의 2.0, 아우터 1.0. Long: 아우터 5.0, 스커트 4.0).

## 결정

1. **실행 사전 `lumi-pi-v5.1`을 기본으로 한다.** `scripts/build_lumi_pi_unified.py --export-runtime`이 기존 통합 jsonl에서 사전(`output/feature-map/lumi-pi-v5.1.json`)과 `lumi-catalog-v1` 가져오기 파일을 만든다. 다시 빌드하지 않고 모델도 부르지 않는다. 품목은 `Top`·`Bottom`·`Outer`·`Skirt`다. 품목군마다 쓰는 값은 `values_by_garment_type`에 두어 사전이 품목에 맞지 않는 값을 거부한다(예: 스커트의 Fit).
2. **기장 점수는 품목군별 표를 그대로 쓴다.** 점수 체계를 하나로 통일하지 않는다. `value_shape.scale`에 품목군(top·bottom·outer·skirt)별 표를 두고, 상품의 `Length.scale`(품목군 이름)로 표를 고른다. 질문 루프의 상대 조정은 이 표로 값과 목표를 정한다. 통일하면 상품 점수를 다시 매겨야 하고, 품목마다 간격이 달라 "조금 더 / 훨씬"이 같은 값이 되며, 상의(소매)와 다른 품목(몸판·밑단)의 뜻 차이를 숨기게 된다.
3. **점수·색·가격의 저장 위치는 그대로 둔다.** 상품의 `raw_metadata.pi_v3`(`price_krw`, 축별 `score`·`scale`·`colors`)다. 키 이름은 graph 엔진이 0016 이후 읽는 이름을 유지한다.
4. **가져오기 파일을 12 MiB 이하 조각으로 나눈다.** `catalog-import`의 16 MiB 입력 제한은 그대로 두고 조각 파일(`lumi-pi-v5.1-import-NN.jsonl`)을 차례로 가져온다. 가져오기는 상품 ID로 갱신하므로 결과는 한 번에 가져온 것과 같다.
5. **공용(unisex) 상품은 남성·여성 어느 쪽을 골라도 보인다.** 성별 값이 없는 상품은 이전처럼 "전체"에서만 보인다([ADR 0015](0015-top-memory-warm-start.md)).
6. 같은 값이 한 축에 두 번 들어간 슬롯(남성 아우터 Color 76개, 팔레트 두 군집이 같은 이름)은 빌드·내보내기에서 한 번으로 줄인다.

## 대안

- **기장 점수 체계를 하나로 통일한다**: 결정 2의 이유로 채택하지 않았다.
- **가져오기 크기 제한을 올린다**: 입력 검증 경계를 바꾸지 않고 조각으로 처리할 수 있다.
- **`lumi-pi-v3`을 기본으로 두고 v5.1을 선택 사항으로 둔다**: 최종 데이터가 v5.1이라 기본값을 바꾼다. v3은 이전 결과 재현용으로 남긴다.

## 영향

- 확인: 9,202개를 저장소 밖 DB로 가져와 Map을 만들었고, 원본에 값이 있는 축이 모두 Map에 들어갔다(중복을 줄인 Color 76개만 표기가 다름). fake provider로 네 품목군마다 8턴을 돌려 사진 선택지·글 질문·이미지 여러 장·공통점 칩·기준 이미지 조정·비교 제안이 나오고, 한국어 라벨과 실제 이미지가 보이는 것을 확인했다.
- 모델 값은 사람이 검수하지 않았다. 축 중요도는 품목 공통 기본표다([#41](https://github.com/jongrionro-debug/HCI_HANDSOME/issues/41)).
- 이미지 3.4 GB는 저장소 밖 이미지 root에 같은 상대 경로(`lumi-pi-unified/`)로 둔다.
