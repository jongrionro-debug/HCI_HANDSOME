"""Render the conceptual memory figure as editable SVG and vector PDF.

The figure describes the design, not measured participant data.
Usage: bundled Python render_figure.py
Render the resulting PDF with pdftoppm for visual verification and the PNG.
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parent
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT = "LumiKorean"
pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))

W, H = 1800, 1180
d = Drawing(W, H)

INK = "#18232D"
MUTED = "#4A5662"
BORDER = "#AAB3BC"
TEAL = "#176C62"
TEAL_BG = "#EDF6F2"
BLUE = "#215D91"
BLUE_BG = "#EDF3FA"
GOLD = "#8C5D17"
GOLD_BG = "#FFF6E6"


def rect(x, y, w, h, fill="#FFFFFF", stroke=BORDER, radius=8, sw=2):
    d.add(Rect(x, H - y - h, w, h, rx=radius, ry=radius,
               fillColor=HexColor(fill), strokeColor=HexColor(stroke), strokeWidth=sw))


def text(x, y, s, size=27, color=INK, anchor="start", max_width=None):
    if max_width is not None:
        width = pdfmetrics.stringWidth(s, FONT, size)
        if width > max_width:
            raise ValueError(f"Text exceeds width {max_width}: {s} ({width:.1f})")
    d.add(String(x, H - y, s, fontName=FONT, fontSize=size,
                 fillColor=HexColor(color), textAnchor=anchor))


def lines(x, y, rows, size=27, leading=38, color=INK, max_width=None):
    for i, row in enumerate(rows):
        text(x, y + i * leading, row, size=size, color=color, max_width=max_width)


def arrow(points, color=MUTED, dashed=False, width=2.8, head=11):
    for a, b in zip(points, points[1:]):
        line = Line(a[0], H - a[1], b[0], H - b[1],
                    strokeColor=HexColor(color), strokeWidth=width)
        if dashed:
            line.strokeDashArray = [10, 8]
        d.add(line)
    a, b = points[-2:]
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    bx = b[0] - head * math.cos(angle)
    by = b[1] - head * math.sin(angle)
    side = head * 0.48
    d.add(Polygon([b[0], H - b[1],
                   bx + side * math.sin(angle), H - by + side * math.cos(angle),
                   bx - side * math.sin(angle), H - by - side * math.cos(angle)],
                  fillColor=HexColor(color), strokeColor=None))


def card(x, y, w, h, title, rows, fill="#FFFFFF", stroke=BORDER,
         title_color=INK, body_size=27, leading=38):
    rect(x, y, w, h, fill=fill, stroke=stroke)
    text(x + 24, y + 48, title, size=31, color=title_color, max_width=w - 48)
    lines(x + 24, y + 91, rows, size=body_size, leading=leading,
          color=INK, max_width=w - 48)


rect(0, 0, W, H, stroke="#FFFFFF", radius=0, sw=0)
text(40, 48, "a   사용자 의미의 보존과 요청별 해석", size=34)

# Memory Layer: the shared representation is distinct from the requested map.
rect(420, 98, 480, 576, fill="#F8FAFB", stroke="#B8C1C8", radius=12)
text(444, 138, "Memory Layer · 표현 / 근거 / 범위", size=28, max_width=435)

card(444, 165, 432, 169, "장기 기억", [
    "이후 활용에 동의한 선호",
    "예: 평소 바지는 여유 핏",
    "다음 요청에도 조건별 활용",
], fill=TEAL_BG, stroke=TEAL, title_color=TEAL, body_size=27, leading=32)

rect(444, 364, 432, 72, fill=GOLD_BG, stroke=GOLD)
text(660, 396, "내용 확인 + 별도 장기 활용 동의", size=26,
     color=GOLD, anchor="middle", max_width=400)
text(660, 422, "선택한 항목만 추가·구체화·교체", size=24,
     color=GOLD, anchor="middle", max_width=400)
arrow([(660, 364), (660, 334)], color=GOLD, head=10)

card(444, 466, 432, 169, "단기 기억", [
    "이번 요청의 조건과 예외",
    "예: 오늘 바지는 슬림 핏",
    "새 요청에는 자동 이월 안 함",
], fill=BLUE_BG, stroke=BLUE, title_color=BLUE, body_size=27, leading=32)
arrow([(660, 466), (660, 436)], color=GOLD, head=10)
text(660, 658, "반복 선택·요청 종료만으로 장기 변경 안 함", size=23,
     color=MUTED, anchor="middle", max_width=445)

# Input and confirmation: confirmation need not add an extra click for clear text.
card(40, 466, 300, 169, "입력·선택 근거", [
    "요청·설명·수정",
    "이미지·부분 선택",
    "선택 이유는 가설",
], body_size=27, leading=32)
arrow([(340, 553), (444, 553)], color=BLUE)
text(392, 492, "의미 추출", size=22, color=BLUE, anchor="middle")
text(392, 521, "내용 확인", size=22, color=BLUE, anchor="middle")

# Selected memories are interpreted only for this target and situation.
card(990, 165, 360, 216, "관련 기억 조회", [
    "대상·상황·유효 상태",
    "현재 요청의 조건 우선",
    "같은 순위 충돌은 확인",
    "장기 원본은 보존",
], body_size=27, leading=35)
arrow([(876, 248), (990, 248)], color=TEAL)
arrow([(876, 553), (944, 553), (944, 326), (990, 326)], color=BLUE)

card(990, 466, 360, 169, "요청별 선호 해석", [
    "User Preference Map",
    "확정 조건 / 가설 / 미정",
    "의미와 속성 해석 분리",
], fill="#F4F5F7", body_size=27, leading=32)
arrow([(1170, 381), (1170, 466)])
text(1190, 430, "요청마다 재구성", size=25, color=MUTED)

card(1440, 466, 320, 169, "추천·이미지 선택", [
    "상품 속성과 대조",
    "전체·부분 선택",
    "설명·확인·재추천",
], body_size=27, leading=32)
arrow([(1350, 553), (1440, 553)])

# The callout keeps the memory/interpretation boundary visible.
lines(1440, 213, ["해석 결과 ≠ 장기 갱신", "Map이 바뀌어도", "사용자의 의미는 보존"],
      size=28, leading=43, color=MUTED)
arrow([(1600, 635), (1600, 719), (190, 719), (190, 635)],
      color=MUTED, dashed=True, head=10)
rect(785, 687, 420, 54, fill="#FFFFFF", stroke="#FFFFFF", sw=0)
text(995, 722, "피드백 → 이번 요청의 선호 구체화", size=26,
     anchor="middle", color=MUTED, max_width=415)

# A single longitudinal example: no empirical outcomes are encoded.
d.add(Line(40, H - 780, 1760, H - 780,
           strokeColor=HexColor("#CBD2D8"), strokeWidth=2))
text(40, 831, "b   반복 사용 예시: 일시적 요구와 지속적 변화의 구분", size=34)

xs = [40, 480, 920, 1360]
cw, cy, ch = 400, 865, 224
stages = [
    ("01  평소 취향", TEAL_BG, TEAL, [
        "내용 확인 + 장기 활용 동의",
        "바지: 여유 핏",
        "색상: 네이비",
    ]),
    ("02  오늘만 다른 요구", BLUE_BG, BLUE, [
        "오늘 발표에는 슬림 핏",
        "단기: 슬림 / 장기: 여유",
        "이번 추천: 슬림 + 네이비",
    ]),
    ("03  다음 요청", TEAL_BG, TEAL, [
        "새 요청에 추가 조건 없음",
        "이전 단기는 적용하지 않음",
        "이번 추천: 여유 + 네이비",
    ]),
    ("04  동의한 지속적 변화", GOLD_BG, GOLD, [
        "앞으로도 슬림 핏을 선호",
        "새 내용 확인 + 활용 동의",
        "장기 핏 교체 / 네이비 유지",
    ]),
]
for x, (title, bg, stroke, rows) in zip(xs, stages):
    card(x, cy, cw, ch, title, rows, fill=bg, stroke=stroke,
         title_color=stroke, body_size=27, leading=45)
for x in xs[:-1]:
    arrow([(x + cw + 3, 980), (x + cw + 36, 980)], color=MUTED, width=2, head=8)

text(460, 1136, "일시적 예외 후 기존 취향 재적용", size=28,
     color=TEAL, anchor="middle")
text(1340, 1136, "확인·동의한 변화만 장기 반영", size=28,
     color=GOLD, anchor="middle")

renderSVG.drawToFile(d, str(ROOT / "figure-1-lumi-memory.svg"))
svg_path = ROOT / "figure-1-lumi-memory.svg"
svg = svg_path.read_text(encoding="utf-8")
svg = svg.replace("font-family: LumiKorean;",
                  "font-family: 'Arial Unicode MS', 'Apple SD Gothic Neo', 'Noto Sans CJK KR', sans-serif;")
svg = svg.replace("<defs>",
                  "<title>LUMI의 장단기 의미 기억과 요청별 선호 해석</title>"
                  "<desc>내용 확인과 별도 장기 활용 동의를 분리하고, 현재 요청의 일시적 예외가 "
                  "장기 기억을 변경하지 않는 설계. 아래 네 단계는 가상의 반복 사용 예시.</desc><defs>", 1)
svg_path.write_text(svg, encoding="utf-8")
# Use a standard wide figure width (10 inches); text and lines remain vector.
scale = 720 / W
d.scale(scale, scale)
d.width = 720
d.height = H * scale
canvas = Canvas(str(ROOT / "figure-1-lumi-memory.pdf"), pagesize=(d.width, d.height))
canvas.setTitle("LUMI: semantic memory, request-specific interpretation and consent")
canvas.setAuthor("LUMI research project")
renderPDF.draw(d, canvas, 0, 0)
canvas.showPage()
canvas.save()
print("Rendered editable SVG and vector PDF")
