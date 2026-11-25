"""Защищённое изменение контуров отверстий и экспериментальные засечки.

Использует только fontTools. Алгоритм контуров основан на аппроксимации
кривых и минимальном расстоянии между внешним и внутренним контурами.
Векторные формы не заменяются растровыми изображениями.

Ограничения:
- Работаем с простыми (декомпозированными) TrueType-глифами.
- Поиск засечек рассчитан на ограниченный список символов.
- Объединение дополнительных контуров рекомендуется делать через skia-pathops.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite, radians, tan

from fontTools.pens.basePen import BasePen


@dataclass(frozen=True)
class SerifSettings:
    style: str = "none"
    length: float = 0.045
    thickness: float = 0.035
    bracket: float = 0.025
    angle: float = 0.0

    def validate(self):
        if not isinstance(self.style, str) or self.style not in {"none", "slab", "wedge", "bracket"}:
            raise ValueError("serif_style: none, slab, wedge или bracket")
        for key, val, low, high in (
            ("serif_length", self.length, .005, .12),
            ("serif_thickness", self.thickness, .005, .09),
            ("serif_bracket", self.bracket, 0, .09),
            ("serif_angle", self.angle, -25, 25),
        ):
            if type(val) not in (float, int) or not low <= val <= high or not isfinite(val):
                raise ValueError(f"{key}: допустимы числа от {low} до {high}")


# Засечки ставятся только в местах, где понятна геометрия прямых штрихов.
_STEMS = {
    "H": ("l", "r"), "I": ("c",), "L": ("l",),
    "E": ("l",), "F": ("l",), "T": ("c",),
    "Н": ("l", "r"), "П": ("l", "r"), "Г": ("l",),
    "Т": ("c",), "Ш": ("l", "c", "r"),
    "І": ("c",), "Ӏ": ("c",),
}
_BOTTOM_ONLY = set("TТFГ")


def _contours(glyph):
    """Контуры в формате (начало, конец, ориентированная площадь, bbox)."""
    if glyph.numberOfContours <= 0:
        return []
    result = []
    start = 0
    for end in glyph.endPtsOfContours:
        points = [glyph.coordinates[i] for i in range(start, end+1)]
        if len(points) >= 3:
            area2 = sum(x1*y2 - x2*y1 for (x1,y1),(x2,y2) in zip(points, points[1:] + points[:1]))
            xs, ys = zip(*points)
            result.append((start,end,area2/2,(min(xs),min(ys),max(xs),max(ys))))
        start=end+1
    return result


def _is_interior(outer, inner, eps=0):
    l,b,r,t = outer
    x0,y0,x1,y1 = inner
    return l+eps < x0 and b+eps < y0 and x1 < r-eps and y1 < t-eps


class _FlattenPen(BasePen):
    """Превращает контуры из линий/квадратичных кривых в точки для измерений.

    Важное отличие от предыдущего приближения: контролируем расстояние
    по реальному изгибу кривой, а не только по bounding-box.
    """
    def __init__(self):
        super().__init__(glyphSet=None)
        self.contours: list[list[tuple[float,float]]] = []
        self.current: list[tuple[float,float]] = []

    def _moveTo(self, pt):
        self.current = [tuple(pt)]

    def _lineTo(self, pt):
        self.current.append(tuple(pt))

    def _qCurveToOne(self, control, end):
        start = self._getCurrentPoint()
        for k in range(1, 7):
            t = k / 6
            a=(1-t)**2
            b=2*(1-t)*t
            c=t*t
            self.current.append((a*start[0]+b*control[0]+c*end[0],
                                 a*start[1]+b*control[1]+c*end[1]))

    def _curveToOne(self, c1, c2, end):
        start = self._getCurrentPoint()
        for k in range(1, 9):
            t=k/8
            a=(1-t)**3; b=3*(1-t)**2*t; c=3*(1-t)*t*t; d=t**3
            self.current.append((a*start[0]+b*c1[0]+c*c2[0]+d*end[0],
                                 a*start[1]+b*c1[1]+c*c2[1]+d*end[1]))

    def _closePath(self):
        if self.current:
            if self.current[0] == self.current[-1]:
                self.current.pop()
            self.contours.append(self.current)
        self.current=[]

    def _endPath(self):
        self._closePath()


def _flatten(glyph):
    pen = _FlattenPen()
    glyph.draw(pen, None)
    return pen.contours


def _point_segment_dist2(p, a, b):
    vx, vy = b[0]-a[0], b[1]-a[1]
    denom = vx*vx+vy*vy
    if denom < 1e-8:
        return (p[0]-a[0])**2+(p[1]-a[1])**2
    t = max(0.0,min(1.0,((p[0]-a[0])*vx+(p[1]-a[1])*vy)/denom))
    return (p[0]-a[0]-t*vx)**2 + (p[1]-a[1]-t*vy)**2


def _polyline_clearance(poly1, poly2):
    """Приближённая кратчайшая дистанция между двумя замкнутыми контурами.

    Кроме точек используем сегменты, чтобы учитывать узкие места кривых.
    """
    best = float("inf")
    for left, right in ((poly1,poly2),(poly2,poly1)):
        edges=list(zip(right,right[1:]+right[:1]))
        for pt in left:
            for a,b in edges:
                dist2 = _point_segment_dist2(pt,a,b)
                if dist2<best:
                    best=dist2
    return best**0.5


def _scaled_poly(poly, center, scale):
    cx,cy=center
    return [(cx+(x-cx)*scale,cy+(y-cy)*scale) for x,y in poly]


def change_counter_size(glyph, counter_scale: float, em: int = 1000,
                        stats: dict | None = None) -> int:
    """Один ползунок просветов для всех букв — универсальная геометрия.

    Совместимый интерфейс со старым ``advanced_generator.py``.
    Точная логика вынесена в ``engine/counter_geometry.py``.
    """
    from engine.counter_geometry import change_counter_size_uniform
    return change_counter_size_uniform(glyph, counter_scale, em, stats)


def _horizontal_intervals(outlines, y):
    """Возвращает горизонтальные интервалы заливки на заданной высоте.

    Заполнение оцениваем правилом even-odd для простых латинских/русских букв.
    """
    hits=[]
    for outline in outlines:
        for (x1,y1),(x2,y2) in zip(outline,outline[1:]+outline[:1]):
            if (y1<=y<y2) or (y2<=y<y1):
                hits.append(x1+(y-y1)*(x2-x1)/(y2-y1))
    hits.sort()
    return [(hits[i],hits[i+1]) for i in range(0,len(hits)-1,2) if hits[i+1]>hits[i]+1]


def _vertical_extreme(outlines, x, bottom=True):
    ys=[]
    for outline in outlines:
        for (x1,y1),(x2,y2) in zip(outline,outline[1:]+outline[:1]):
            if (x1<=x<x2) or (x2<=x<x1):
                ys.append(y1+(x-x1)*(y2-y1)/(x2-x1))
    if not ys: return None
    return min(ys) if bottom else max(ys)


def _append_contour(glyph, points, flags, outer_sign):
    """Вставляет один замкнутый контур с правильным направлением обхода."""
    area2=sum(x1*y2-x2*y1 for (x1,y1),(x2,y2) in zip(points,points[1:]+points[:1]))
    if area2*outer_sign<0:
        points=list(reversed(points)); flags=list(reversed(flags))
    start=len(glyph.coordinates)
    glyph.coordinates.extend([(round(x),round(y)) for x,y in points])
    glyph.flags.extend(bytearray(flags))
    glyph.endPtsOfContours.append(start+len(points)-1)
    glyph.numberOfContours+=1


def _serif_shape(x,y,direction,em,stem_w,settings):
    """Строим форму, масштабируя засечку относительно измеренного штриха.

    Возвращаем TrueType-точки и признаки on-curve/off-curve.
    Форма bracket содержит настоящие квадратичные кривые.
    """
    # На ExtraLight/Thin длина не должна быть во много раз больше штриха.
    extension=min(em*settings.length,stem_w*1.25+em*.012)
    thickness=min(em*settings.thickness,max(2,stem_w*1.05))
    join=min(em*settings.bracket,stem_w*.75)
    half=stem_w*.5
    xleft=x-half-extension
    xright=x+half+extension
    inner_y=y+direction*thickness
    shift=tan(radians(settings.angle))*thickness
    if settings.style=="slab":
        points=[(xleft,y),(xright,y),(xright,inner_y),(xleft,inner_y)]
        flags=[1]*4
    elif settings.style=="wedge":
        bevel=min(extension*.65,em*.03)
        points=[(xleft,y),(xright,y),(xright-shift-bevel,inner_y),
                (xleft+shift+bevel,inner_y)]
        flags=[1]*4
    else: # bracket — плавный переход к телу штриха
        shoulder_y=inner_y+direction*join
        points=[(xleft,y),(xright,y),
                (xright-shift,inner_y),
                (x+half+join,inner_y),  # off-curve контроль для сопряжения
                (x+half,shoulder_y),
                (x-half,shoulder_y),
                (x-half-join,inner_y), # off-curve
                (xleft+shift,inner_y)]
        flags=[1,1,1,0,1,1,0,1]
    return points, flags


def add_serifs(glyph, character: str, em: int, settings: SerifSettings,
               stats: dict | None = None) -> int:
    """Добавляет засечки только к распознанным вертикальным окончаниям.

    Измерение штриха по пересечениям кривых точнее, чем старый расчёт
    по общей ширине bbox. Для наклонных/неоднозначных форм пропускаем
    сомнительные окончания вместо некрасивых огромных элементов.
    """
    if settings.style=="none" or character not in _STEMS:
        return 0
    contours=_contours(glyph)
    if not contours:
        return 0
    outlines=_flatten(glyph)
    if not outlines: return 0
    outer_sign=1 if max(contours,key=lambda c:abs(c[2]))[2]>0 else -1
    coords=glyph.coordinates
    xs=[p[0] for p in coords]; ys=[p[1] for p in coords]
    minx,maxx,miny,maxy=min(xs),max(xs),min(ys),max(ys)
    height=maxy-miny
    if height<em*.30:
        return 0
    added=0
    for bottom in (True,False):
        if not bottom and character in _BOTTOM_ONLY:
            continue
        y_sample=miny+height*(.10 if bottom else .90)
        bands=_horizontal_intervals(outlines,y_sample)
        # Короткие/очень тонкие артефакты от пересечений не используем.
        bands=[(a,b) for a,b in bands if b-a>=max(3,em*.006)]
        selected=[]
        for item in _STEMS[character]:
            if not bands:
                break
            if item=="l":
                candidate=bands[0]
            elif item=="r":
                candidate=bands[-1]
            else:
                candidate=min(bands,key=lambda p:abs((p[0]+p[1])/2-(minx+maxx)/2))
            if candidate not in selected:
                selected.append(candidate)
        if len(selected)<len(_STEMS[character]):
            if stats is not None:
                stats["ambiguous_stems"]=stats.get("ambiguous_stems",0)+1
            continue
        for a,b in selected:
            stem_w=b-a
            if stem_w<=0 or stem_w>em*.20:
                if stats is not None:
                    stats["ambiguous_stems"]=stats.get("ambiguous_stems",0)+1
                continue
            x=(a+b)/2
            y=_vertical_extreme(outlines,x,bottom)
            if y is None or abs(y-(miny if bottom else maxy))>em*.08:
                if stats is not None:
                    stats["ambiguous_stems"]=stats.get("ambiguous_stems",0)+1
                continue
            points,flags=_serif_shape(x,y,+1 if bottom else -1,em,stem_w,settings)
            _append_contour(glyph,points,flags,outer_sign)
            added+=1
    return added
