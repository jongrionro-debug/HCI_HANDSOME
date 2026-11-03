"""Draw the current LUMI interaction loop as an editable SVG and a crisp PNG."""
from pathlib import Path
from html import escape
import math

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, SCALE = 2160, 1470, 2
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
COLORS = {
    "ink": "#253540", "muted": "#60717C", "edge": "#6B7D88",
    "memory": ("#F3EFF9", "#806799"), "map": ("#EEF5FA", "#4D7D9E"),
    "hypothesis": ("#FFF5E2", "#AD8138"), "user": ("#EDF5F1", "#467E67"),
    "plain": ("#F8FAFB", "#7A8992"), "end": ("#F8F5EF", "#93836B"),
}
canvas = Image.new("RGB", (W * SCALE, H * SCALE), "white")
draw = ImageDraw.Draw(canvas)
parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
         '<title id="title">LUMI: 사용자 입력, 추천과 메모리 갱신의 전체 흐름</title>',
         '<desc id="desc">입력과 관련 장단기 기억으로 사용자 목표 PI와 FEA를 정리한다. FEA에서 PI 가설을 만들고 상품 PI를 비교해 이미지를 추천한다. 이미지 선택과 선택 사항인 이유를 해석해 단기 기억과 목표 Map을 갱신한다. 대화 종료 후 내용 확인과 별도 동의를 거친 내용만 장기 기억으로 저장한다.</desc>',
         '<rect width="2160" height="1470" fill="white"/>']


def font(size, bold=False):
    return ImageFont.truetype(FONT, round(size * SCALE), index=4 if bold else 0)


def rect(x, y, w, h, fill, stroke, radius=16, width=2):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')
    draw.rounded_rectangle((x*SCALE, y*SCALE, (x+w)*SCALE, (y+h)*SCALE), radius*SCALE,
                           fill=fill, outline=stroke, width=round(width*SCALE))


def text(x, y, value, size=24, color=None, bold=False, align="left"):
    color = color or COLORS["ink"]
    f = font(size, bold)
    anchor = {"left": "start", "center": "middle", "right": "end"}[align]
    parts.append(f'<text x="{x}" y="{y}" font-family="Apple SD Gothic Neo, Noto Sans CJK KR, sans-serif" font-size="{size}" font-weight="{600 if bold else 400}" fill="{color}" text-anchor="{anchor}" dominant-baseline="text-before-edge">{escape(value)}</text>')
    length = draw.textlength(value, font=f)
    px = x*SCALE - (length/2 if align == "center" else length if align == "right" else 0)
    draw.text((px, y*SCALE), value, font=f, fill=color, anchor="lt")


def label(x, y, value, color=None, size=21):
    f = font(size)
    width = draw.textlength(value, font=f) / SCALE + 18
    rect(x-9, y-2, width, size+11, "white", "white", radius=3, width=0)
    text(x, y, value, size=size, color=color or COLORS["muted"])


def arrow(points, color=None, width=2.8, dashed=False, bridge=False):
    color = color or COLORS["edge"]
    path = "M " + " L ".join(f"{x} {y}" for x, y in points)
    if bridge:
        parts.append(f'<path d="{path}" fill="none" stroke="white" stroke-width="9"/>')
        draw.line([(x*SCALE, y*SCALE) for x, y in points], fill="white", width=9*SCALE)
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{dash}/>')
    if dashed:
        for (x1,y1),(x2,y2) in zip(points, points[1:]):
            length = math.hypot(x2-x1,y2-y1)
            for at in range(0, math.ceil(length), 18):
                a,b = at/length,min(at+10,length)/length
                draw.line(((x1+(x2-x1)*a)*SCALE,(y1+(y2-y1)*a)*SCALE,
                           (x1+(x2-x1)*b)*SCALE,(y1+(y2-y1)*b)*SCALE),fill=color,width=round(width*SCALE))
    else:
        draw.line([(x*SCALE,y*SCALE) for x,y in points],fill=color,width=round(width*SCALE),joint="curve")
    (x1,y1),(x2,y2) = points[-2:]
    angle = math.atan2(y2-y1,x2-x1)
    tri = [(x2,y2)] + [(x2-13*math.cos(angle+d),y2-13*math.sin(angle+d)) for d in (-.43,.43)]
    parts.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in tri)+f'" fill="{color}"/>')
    draw.polygon([(x*SCALE,y*SCALE) for x,y in tri],fill=color)


def box(x,y,w,h,title,lines,kind="plain",title_size=28,line_size=23):
    fill,stroke = COLORS[kind]
    rect(x,y,w,h,fill,stroke)
    text(x+24,y+20,title,title_size,bold=True)
    for i,line in enumerate(lines):
        text(x+24,y+66+i*32,line,line_size,color=COLORS["muted"])


# Figure heading and legend.
text(60,38,"LUMI · 입력에서 추천과 기억 갱신까지",40,bold=True)
text(60,94,"텍스트와 이미지 선택으로 원하는 상품을 구체화하는 반복 흐름",24,color=COLORS["muted"])
for x,kind,name in ((1470,"memory","기억"),(1615,"map","상품 조건"),(1795,"hypothesis","연결 가설"),(1975,"user","사용자")):
    fill,stroke = COLORS[kind]
    rect(x,54,18,18,fill,stroke,radius=3,width=1.5)
    text(x+29,48,name,23)

# Connectors are below all boxes, with explicit return routes outside the flow.
arrow([(330,280),(420,280)])
arrow([(770,270),(840,270)])
arrow([(770,505),(820,505),(820,310),(840,310)],color=COLORS["memory"][1])
arrow([(1040,295),(1110,295)])
arrow([(1580,280),(1660,280)],color=COLORS["hypothesis"][1])
arrow([(1235,420),(1235,530)],color=COLORS["map"][1])
arrow([(1700,545),(1640,545),(1640,600),(1580,600)],color=COLORS["map"][1])
arrow([(1345,670),(1345,770)])
arrow([(2080,275),(2130,275),(2130,720),(1500,720),(1500,770)],color=COLORS["hypothesis"][1])
arrow([(1110,855),(1010,855)])
arrow([(630,855),(530,855)],color=COLORS["user"][1])
arrow([(130,860),(50,860),(50,150),(595,150),(595,180)],color=COLORS["user"][1],width=3.3)
arrow([(820,940),(820,1090)],color=COLORS["end"][1])
arrow([(970,1150),(1060,1150)],color=COLORS["end"][1])
arrow([(1420,1150),(1490,1150)],color=COLORS["end"][1])
arrow([(1720,1150),(1800,1150)],color=COLORS["memory"][1])
arrow([(1605,1235),(1605,1280)],color=COLORS["end"][1])
arrow([(1945,1215),(1945,1390),(80,1390),(80,505),(420,505)],
      color=COLORS["memory"][1],width=2.7,dashed=True,bridge=True)

label(195,132,"이번 요청의 기억 갱신",color=COLORS["user"][1])
label(1250,470,"찾을 상품 조건",color=COLORS["map"][1])
label(1665,688,"가설의 조건 유무를 비교",color=COLORS["hypothesis"][1])
label(837,1000,"마무리할 때",color=COLORS["end"][1])
label(1732,1110,"동의",color=COLORS["memory"][1])
label(1625,1243,"미동의",color=COLORS["end"][1],size=20)
label(610,1353,"동의한 기억은 다음 요청에서 다시 참고",color=COLORS["memory"][1],size=23)

box(60,210,270,140,"사용자 첫 요청",["네이비 슬랙스를", "편하게 입고 싶어요"],kind="user",line_size=22)
box(420,180,350,180,"입력 해석 · 단기 메모리",["이번 요청의 요구·상황", "선택·수정·확인 중인 내용", "입력 근거와 함께 보존"],kind="memory",title_size=26,line_size=22)
box(420,430,350,150,"장기 메모리",["이전 세션에서 확인하고", "다음 활용에 동의한 취향"],kind="memory",line_size=22)
rect(840,245,200,100,*COLORS["plain"])
text(940,265,"관련 기억 선택",24,bold=True,align="center")
text(940,300,"확인한 내용 반영",22,align="center")

rect(1110,150,470,270,*COLORS["map"])
text(1134,169,"사용자 목표 Feature Map",29,bold=True)
rect(1130,223,205,130,"white","#C1D6E5",radius=10,width=1.5)
rect(1355,223,205,130,"white","#C1D6E5",radius=10,width=1.5)
text(1150,241,"상품 조건 (PI)",25,bold=True)
text(1150,284,"종류 · 색 · 핏",23)
text(1150,318,"직접 말한 조건",21,color=COLORS["muted"])
text(1373,241,"이유·맥락 (FEA)",24,bold=True)
text(1373,284,"편안함 · 용도",23)
text(1373,318,"원하는 이유·필요",21,color=COLORS["muted"])
text(1134,375,"현재 요구 우선 · 모르는 값은 미정",22,color=COLORS["muted"])
box(1660,180,420,190,"FEA → PI 연결 가설",["편안함을 와이드핏으로", "구체화해도 될까?", "아직 확정하지 않은 해석"],kind="hypothesis",line_size=23)
box(1700,470,380,150,"상품별 Feature Map",["확인된 상품 조건 (PI)", "종류 · 색 · 핏 · 소재 등"],kind="map",line_size=23)
box(1110,530,470,140,"상품 조건 비교·검색",["사용자 목표 PI ↔ 상품 PI", "알려진 필수 조건부터 유지"],line_size=23)
box(1110,770,470,170,"추천·비교 아이템 제시",["가설의 PI 값이 있는 상품과", "없는 것으로 확인된 상품 비교"],kind="plain",line_size=23)
box(630,770,380,170,"사용자 응답",["이미지 선택 + 이유·수정", "텍스트는 선택 사항"],kind="user",line_size=23)

rect(130,730,400,274,*COLORS["user"])
text(154,751,"선택·설명 해석",29,bold=True)
for y,head,body in ((804,"가설의 조건을 명확히 선택","→ 해당 PI 해석 확인"),
                    (866,"이유·수정을 함께 보냄","→ 기억 후보 정리 · 내용 확인"),
                    (928,"없음·모르겠음·이유 불명확","→ 확인 전까지 미확인 유지")):
    text(154,y,head,21,bold=True)
    text(154,y+28,body,21,color=COLORS["muted"])
text(130,1023,"선택 사실·이유·상황·확인 상태를 보존",21,color=COLORS["muted"])

box(630,1090,340,120,"아이템 선택(선택 사항)",["+ 대화 종료"],kind="end",title_size=26,line_size=25)
box(1060,1080,360,140,"종료 요약·내용 확인",["기존 기억 후보를 검토", "다음에 활용할 내용 선택"],kind="end",title_size=27,line_size=22)
diamond=[(1605,1065),(1720,1150),(1605,1235),(1490,1150)]
parts.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in diamond)+f'" fill="{COLORS["end"][0]}" stroke="{COLORS["end"][1]}" stroke-width="2"/>')
draw.polygon([(x*SCALE,y*SCALE) for x,y in diamond],fill=COLORS["end"][0],outline=COLORS["end"][1],width=2*SCALE)
text(1605,1115,"이후 활용에",24,bold=True,align="center")
text(1605,1148,"동의하나요?",24,bold=True,align="center")
rect(1800,1085,290,130,*COLORS["memory"])
text(1945,1111,"동의한 내용만",26,bold=True,align="center")
text(1945,1152,"장기 메모리로 저장",25,bold=True,align="center")
rect(1490,1280,230,70,*COLORS["end"])
text(1605,1300,"저장 없이 마침",24,align="center")

text(100,1430,"실선: 이번 요청의 처리 흐름     점선: 이후 요청에서의 기억 활용",21,color=COLORS["muted"])
parts.append("</svg>")
(ROOT/"lumi-interaction-loop.svg").write_text("\n".join(parts),encoding="utf-8")
canvas.save(ROOT/"lumi-interaction-loop.png",dpi=(240,240))
print("Created SVG and PNG:",W,"×",H,"(PNG at 2×)")
