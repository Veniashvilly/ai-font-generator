"""Универсальное изменение внутренних просветов TrueType-глифов.

Один ползунок ``counter_scale`` управляет ВСЕМИ отверстиями глифа.
Алгоритм НЕ привязан к именам букв: A, B, O, В, 8 и т.д. проходят
одну и ту же геометрическую проверку.

Геометрия на уровне контуров: исходный TTF не меняется, растеризация
для расчётов не используется. Кривые приближаются полилиниями только
для поиска расстояний; сохраняются оригинальные квадратичные кривые.

Ограничения: приближённая геометрия. Это НЕ сертификация качества TTF.
"""
from __future__ import annotations

from math import isfinite

from engine.advanced_effects import _contours, _flatten


Point = tuple[float, float]
Polygon = list[Point]

# Декоративные и рукописные глифы могут содержать десятки отдельных
# штрихов и тысячи точек. Проверка расстояний между ВСЕМИ контурами
# становится квадратичной и иногда занимает десятки секунд на одну букву.
# Такие глифы не трогаем алгоритмом внутренних отверстий: лучше честно
# пропустить эффект, чем зависнуть или испортить исходный рисунок.
MAX_COUNTER_CONTOURS = 12
MAX_COUNTER_COORDS = 260
MAX_FLATTENED_POINTS = 540
MAX_PAIR_WORK = 180_000
MAX_RECOVERY_CONTOURS = 5
MAX_RECOVERY_COORDS = 110


def _skip_complex(stats: dict | None, reason: str) -> int:
    if stats is not None:
        stats["skipped"] = stats.get("skipped", 0) + 1
        stats["complexity_skipped"] = True
        stats["skip_reason"] = reason
    return 0


def _bbox(poly: Polygon) -> tuple[float, float, float, float]:
    return (min(p[0] for p in poly), min(p[1] for p in poly),
            max(p[0] for p in poly), max(p[1] for p in poly))


def _area(poly: Polygon) -> float:
    return 0.5 * sum(x*y2-x2*y for (x,y),(x2,y2)
                     in zip(poly, poly[1:]+poly[:1]))


def _point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """Проверка пересечения луча и границы произвольной простой фигуры."""
    x,y = point
    inside = False
    for (x1,y1),(x2,y2) in zip(polygon,polygon[1:]+polygon[:1]):
        if (y1>y)!=(y2>y):
            at_x=x1+(y-y1)*(x2-x1)/(y2-y1)
            if at_x>x:
                inside=not inside
    return inside


def _bbox_contains(outer, inner, tolerance=0.5) -> bool:
    """Допускаем малую неточность аппроксимации кривых (в единицах em).

    Сам факт касания границы мы всё равно перепроверяем геометрически.
    """
    return (outer[0] <= inner[0] + tolerance
            and outer[1] <= inner[1] + tolerance
            and inner[2] <= outer[2] + tolerance
            and inner[3] <= outer[3] + tolerance)


def _contains_contour(parent: Polygon, child: Polygon) -> bool:
    """Нужны bbox и несколько проверочных точек — одного bbox мало."""
    if not _bbox_contains(_bbox(parent),_bbox(child)):
        return False
    selected = sorted(set([0, len(child)//4, len(child)//2, 3*len(child)//4]))
    return all(_point_in_polygon(child[i],parent) for i in selected)


def _point_segment_dist2(p: Point,a: Point,b: Point) -> float:
    vx,vy=b[0]-a[0],b[1]-a[1]
    d=vx*vx+vy*vy
    if d<1e-12:
        return (p[0]-a[0])**2+(p[1]-a[1])**2
    t=max(0.,min(1.,((p[0]-a[0])*vx+(p[1]-a[1])*vy)/d))
    return (p[0]-a[0]-t*vx)**2+(p[1]-a[1]-t*vy)**2


def _cross(a: Point,b: Point,c: Point) -> float:
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _segments_cross(a,b,c,d) -> bool:
    """Обнаруживаем настоящие пересечения рёбер, а не только близкие точки."""
    a1,a2=_cross(a,b,c),_cross(a,b,d)
    b1,b2=_cross(c,d,a),_cross(c,d,b)
    return a1*a2<-1e-8 and b1*b2<-1e-8


def _polyline_clearance(first: Polygon, second: Polygon) -> float:
    """Минимальный зазор по аппроксимации кривых.

    В отличие от v3, отбрасываем сегменты, чьи bounding-box заведомо
    дальше текущей лучшей дистанции. Это не меняет результат расчёта,
    но избавляет от большого числа дорогих проекций точек на отрезки.
    """
    if not first or not second:
        return float("inf")

    best = float("inf")
    # В редких исходниках со взаимно пересекающимися контурами
    # не пытаемся «починить» геометрию масштабированием.
    for poly1, poly2 in ((first, second), (second, first)):
        edges = []
        for a, b in zip(poly2, poly2[1:] + poly2[:1]):
            edges.append((a, b, min(a[0], b[0]), min(a[1], b[1]),
                          max(a[0], b[0]), max(a[1], b[1])))
        radius = float("inf")
        for point in poly1:
            x, y = point
            for a, b, x0, y0, x1, y1 in edges:
                if x < x0 - radius or x > x1 + radius:
                    continue
                if y < y0 - radius or y > y1 + radius:
                    continue
                distance = _point_segment_dist2(point, a, b)
                if distance < best:
                    best = distance
                    radius = best ** 0.5
    return best ** 0.5


def _scale(poly:Polygon, center:Point, factor:float)->Polygon:
    cx,cy=center
    return [(cx+(x-cx)*factor,cy+(y-cy)*factor) for x,y in poly]


def _classify_holes(outlines:list[Polygon]):
    """Ищем вложенные контуры с противоположным направлением обхода.

    Родителя выбираем по площади среди контуров, которые действительно
    содержат отверстие. Поэтому одинаково обрабатываются буквы с одним
    просветом и с несколькими просветами.
    """
    areas=[_area(poly) for poly in outlines]
    holes={}
    for i,poly in enumerate(outlines):
        if len(poly)<3 or abs(areas[i])<1.:
            continue
        options=[]
        for j,outer in enumerate(outlines):
            if i==j or len(outer)<3:
                continue
            if areas[i]*areas[j]>=0 or abs(areas[j])<=abs(areas[i]):
                continue
            if _contains_contour(outer,poly):
                options.append(j)
        if options:
            holes[i]=min(options,key=lambda j:abs(areas[j]))
    return holes


def _candidate_is_safe(
    outlines:list[Polygon], holes:dict[int,int], factor:float,
    min_clearance:dict[int,float],
) -> bool:
    """Проверяем сразу ВСЕ отверстия глифа с одним общим масштабом."""
    candidate=list(outlines)
    for index in holes:
        x0,y0,x1,y1=_bbox(outlines[index])
        center=((x0+x1)/2,(y0+y1)/2)
        candidate[index]=_scale(outlines[index],center,factor)

    for index,parent in holes.items():
        hole=candidate[index]
        if not _contains_contour(candidate[parent],hole):
            return False
        for other,poly in enumerate(candidate):
            if other==index:
                continue
            # Внутри другой буквы/островка нельзя пересечь чужой контур.
            clearance=_polyline_clearance(hole,poly)
            if clearance<min_clearance[index]-0.05:
                return False
    return True


def _possible_overlap(outlines):
    """Быстрая проверка: bbox двух контуров имеют область пересечения.

    Если контуры пространственно разделены (например, точка у i),
    expensive pathops запускать незачем.
    """
    bboxes = [_bbox(p) for p in outlines]
    for i, (x0, y0, x1, y1) in enumerate(bboxes):
        for xx0, yy0, xx1, yy1 in bboxes[i+1:]:
            if min(x1, xx1) > max(x0, xx0) + 1 and min(y1, yy1) > max(y0, yy0) + 1:
                return True
    return False


def _recover_overlapping_contours(glyph):
    """Резервная нормализация пересекающихся контуров через skia-pathops.

    Нужна, если исходный шрифт построен из наложенных фигур вместо
    внешнего контура и отдельного контура отверстия. Не выполняется
    в обычном случае — это помогает сохранять скорость.

    Возвращает НОВЫЙ глиф. Оригинальный объект не изменяется.
    Если skia-pathops не установлен или не может обработать рисунок,
    возвращаем None; никогда не подменяем геометрию непроверенным TTF.
    """
    try:
        import pathops
        from fontTools.pens.ttGlyphPen import TTGlyphPen

        path = pathops.Path()
        glyph.draw(path.getPen(), None)
        path.simplify()
        pen = TTGlyphPen(None)
        path.draw(pen)
        return pen.glyph()
    except (ImportError, Exception):
        # Ошибка не должна прерывать генерацию всего шрифта.
        return None


def _missing_reason(outlines):
    """Диагностика: не утверждаем, что у всех букв есть отдельное отверстие."""
    if len(outlines) < 2:
        return "один контур: отдельное замкнутое отверстие отсутствует"
    areas = [_area(p) for p in outlines]
    for i, child in enumerate(outlines):
        for j, outer in enumerate(outlines):
            if i == j or abs(areas[i]) >= abs(areas[j]):
                continue
            if _contains_contour(outer, child) and areas[i] * areas[j] >= 0:
                return "вложенные контуры с одинаковым направлением"
    return "контуры не образуют отдельное замкнутое отверстие"


def change_counter_size_uniform(glyph,counter_scale:float,em:int=1000,stats:dict|None=None)->int:
    """Глобальный ползунок, адаптивное изменение просветов.

    Все найденные отверстия одного глифа получают ОДИН эффективный
    коэффициент. Это помогает держать верхнюю и нижнюю части B согласованными.
    Если шрифт очень тонкий, эффект будет ослаблен автоматически.

    Возвращает число изменённых отверстий, не число букв.
    """
    if type(counter_scale) not in (int,float) or not isfinite(counter_scale) or not 0.7<=counter_scale<=1.3:
        raise ValueError("counter_scale: диапазон 0.70..1.30")
    if abs(counter_scale - 1) < 1e-8:
        return 0

    # Наличие раздельных контуров проверяем сразу, без дорогих измерений.
    if stats is not None:
        stats["contours_total"] = glyph.numberOfContours
        stats["holes_found"] = 0
        stats["recovery_used"] = False
    if glyph.numberOfContours < 2:
        if stats is not None:
            stats["skip_reason"] = "один контур: отдельное замкнутое отверстие отсутствует"
        return 0

    # Быстрый тест ДО разложения кривых и запуска pathops.
    points = len(glyph.coordinates)
    if glyph.numberOfContours > MAX_COUNTER_CONTOURS or points > MAX_COUNTER_COORDS:
        return _skip_complex(stats, "сложный декоративный глиф: анализ отверстий пропущен")

    outlines = _flatten(glyph)
    flattened = sum(len(poly) for poly in outlines)
    if flattened > MAX_FLATTENED_POINTS or flattened * flattened > MAX_PAIR_WORK:
        return _skip_complex(stats, "слишком много сегментов кривых для безопасного анализа")
    contours = _contours(glyph)
    if len(outlines) != len(contours):
        if stats is not None:
            stats["skipped"] = stats.get("skipped", 0) + 1
            stats["skip_reason"] = "не совпало число контуров при анализе"
        return 0

    holes = _classify_holes(outlines)
    recovered = None
    use_recovered = False
    if (not holes and glyph.numberOfContours <= MAX_RECOVERY_CONTOURS
            and points <= MAX_RECOVERY_COORDS and _possible_overlap(outlines)):
        # В некоторых шрифтах перекрывающиеся фигуры дают отверстие
        # лишь после булевого объединения. Не запускаем pathops
        # для отдельных друг от друга диакритических знаков.
        recovered = _recover_overlapping_contours(glyph)
        if recovered is not None and recovered.numberOfContours >= 2:
            new_outlines = _flatten(recovered)
            new_contours = _contours(recovered)
            if len(new_outlines) == len(new_contours):
                new_holes = _classify_holes(new_outlines)
                if new_holes:
                    outlines, contours, holes = new_outlines, new_contours, new_holes
                    use_recovered = True
                    # До успешного результата пока НЕ трогаем исходный глиф.
                    if stats is not None:
                        stats["recovery_used"] = True
    if not holes:
        if stats is not None:
            stats["skip_reason"] = _missing_reason(outlines)
        return 0

    # Если pathops помог найти отверстие, дальнейшее редактирование
    # выполняем на нормализованной копии. Исходник заменим только в конце.
    target = recovered if use_recovered else glyph

    # Радиус перемещения точки при масштабировании. Используем также
    # off-curve точки: кривая Безье заключена в их выпуклую оболочку.
    radii = {}
    centers = {}
    for idx in holes:
        x0, y0, x1, y1 = _bbox(outlines[idx])
        center = ((x0 + x1) * .5, (y0 + y1) * .5)
        centers[idx] = center
        start, end, _, _ = contours[idx]
        radii[idx] = max(
            ((target.coordinates[j][0] - center[0]) ** 2 +
             (target.coordinates[j][1] - center[1]) ** 2) ** .5
            for j in range(start, end + 1)
        )

    # Один раз измеряем исходные зазоры между контурами.
    # В v3 те же расстояния вычислялись заново при каждом из 11 шагов
    # бинарного поиска: на сложных TTF это занимало десятки секунд.
    pair_gaps = {}
    min_gaps = {}
    for idx in holes:
        minimum = float("inf")
        for j in range(len(outlines)):
            if idx == j:
                continue
            pair = (min(idx, j), max(idx, j))
            if pair not in pair_gaps:
                pair_gaps[pair] = _polyline_clearance(outlines[idx], outlines[j])
            minimum = min(minimum, pair_gaps[pair])
        min_gaps[idx] = minimum

    if counter_scale > 1:
        # Для роста отверстия оставляем не меньше 45% исходного
        # зазора и не меньше 1.8% em. Это немного усиливает эффект
        # на обычных шрифтах, а абсолютный предел защищает тонкие.
        # Пользовательский коэффициент
        # уменьшается НА ВЕСЬ ГЛИФ, а не отдельно на каждое отверстие.
        required = {
            i: max(float(em) * .018, gap * .45)
            for i, gap in min_gaps.items()
        }
        step_limit = counter_scale - 1.0
        for idx in holes:
            for j in range(len(outlines)):
                if j == idx:
                    continue
                pair = (min(idx, j), max(idx, j))
                gap = pair_gaps[pair]
                minimum = max(required[idx], required.get(j, 0.0))
                # Если оба контура — отверстия, оба перемещаются.
                # Для неподвижного внешнего контура второе слагаемое = 0.
                movement = radii[idx] + radii.get(j, 0.0)
                if movement > 1e-9:
                    step_limit = min(step_limit, max(0.0, (gap - minimum) / movement))
        effective = min(float(counter_scale), 1.0 + max(0.0, step_limit))
    else:
        # При уменьшении отверстие не пересекает внешнюю границу, но штрих
        # становится толще. Для Hairline нельзя превратить 10 ед. в 60 ед.
        # Более заметное уменьшение: прирост штриха <= 80% исходного
        # зазора. Слишком тонкие оригиналы по-прежнему ограничиваются.
        effective = float(counter_scale)
        for idx in holes:
            radius = radii[idx]
            gap = min_gaps[idx]
            if radius > 1e-9:
                effective = max(effective, 1.0 - .80 * gap / radius)
            x0, y0, x1, y1 = _bbox(outlines[idx])
            smallest = min(x1-x0, y1-y0)
            if smallest <= 0:
                effective = 1.0
            elif smallest * effective < max(3, em * .012):
                effective = max(effective, min(1.0, max(3, em * .012) / smallest))
        effective = min(1.0, effective)

    if stats is not None:
        stats["requested_scale"]=float(counter_scale)
        stats["effective_scale"]=round(effective,4)
        stats["holes_found"]=len(holes)
        if abs(effective-counter_scale)>0.002:
            stats["limited"]=stats.get("limited",0)+len(holes)
        if abs(effective-1)<.0005:
            stats["skipped"]=stats.get("skipped",0)+len(holes)
    if abs(effective-1)<.0005:
        return 0

    # Точки контуров, включая управляющие off-curve, меняем одной матрицей.
    # Кривые остаются векторными TrueType-кривыми — качество не теряется.
    for idx in holes:
        start,end,_,_ = contours[idx]
        x0,y0,x1,y1=_bbox(outlines[idx])
        cx,cy=(x0+x1)*.5,(y0+y1)*.5
        for j in range(start,end+1):
            x,y=target.coordinates[j]
            target.coordinates[j]=(round(cx+(x-cx)*effective),
                                   round(cy+(y-cy)*effective))

    if use_recovered:
        # Только после успешного применения меняем объект оригинального глифа.
        # caller (advanced_generator.py) продолжит использовать тот же glyph.
        glyph.__dict__.clear()
        glyph.__dict__.update(target.__dict__)
    return len(holes)
