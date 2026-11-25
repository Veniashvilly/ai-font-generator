"""Геометрические эффекты штрихов и углов для TrueType-glyf.

Жирность: локальное смещение точек контура по нормалям, а не масштабирование
целых букв. Этот метод сохраняет квадратичные кривые, но не является точным
оффсетом Безье; на сложных шрифтах результат необходимо проверять.

Скругление: у настоящих углов между прямыми отрезками вставляется кривая
Безье второго порядка. Существующие кривые остаются на месте.
"""
from __future__ import annotations

import math
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates


def _area(points):
    return sum(x1*y2 - x2*y1 for (x1, y1), (x2, y2)
               in zip(points, points[1:] + points[:1])) * 0.5


def _unit(x, y):
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-8 else None


def change_weight(glyph, weight_scale: float, em: int = 1000,
                  stats: dict | None = None) -> int:
    """Изменить толщину, двигая границы ЗАЛИТЫХ областей.

    Внешний и внутренний контуры автоматически смещаются в разные стороны
    из-за противоположного направления обхода. Даже буква H с одним контуром
    теперь утолщается, включая перекладину, а не просто становится крупнее.
    """
    if type(weight_scale) not in (int, float) or not math.isfinite(weight_scale) or not .75 <= weight_scale <= 1.35:
        raise ValueError("weight_scale: допустимо 0.75..1.35")
    if abs(weight_scale - 1.0) < 1e-9 or glyph.numberOfContours <= 0:
        return 0

    # Расстояние смещения в единицах шрифта. Параметр логически относительный,
    # но само смещение одинаковое по всем буквам (равномернее, чем scale).
    shift = (weight_scale - 1.0) * em * 0.11
    coords = glyph.coordinates
    updates = {}
    changed = 0
    moved_points = 0
    # Направление внешнего контура задаёт, по какую сторону находится краска.
    # Внутренние контуры имеют обратный обход, но ВСЕ их границы смещаем
    # в одну сторону относительно направления обхода (в сторону свободного
    # пространства). Иначе отверстия ошибочно расширяются при утолщении.
    start = 0
    contour_areas = []
    for end in glyph.endPtsOfContours:
        contour_areas.append(_area([tuple(coords[i]) for i in range(start,end+1)]))
        start = end + 1
    outer_area = max(contour_areas, key=abs)
    handed = 1.0 if outer_area > 0 else -1.0
    start = 0
    for end in glyph.endPtsOfContours:
        indices = list(range(start, end + 1))
        pts = [tuple(coords[i]) for i in indices]
        start = end + 1
        if len(pts) < 3:
            continue
        signed_area = _area(pts)
        if abs(signed_area) < 1e-5:
            continue
        contour_moved = False
        # Используем ориентацию основного внешнего контура: все области
        # краски сдвигаются с корректным знаком, включая внутренние дыры.
        n = len(pts)
        for local_idx, idx in enumerate(indices):
            previous = pts[(local_idx-1) % n]
            current = pts[local_idx]
            following = pts[(local_idx+1) % n]
            incoming = _unit(current[0]-previous[0], current[1]-previous[1])
            outgoing = _unit(following[0]-current[0], following[1]-current[1])
            if incoming is None or outgoing is None:
                continue
            # Знак берём от основного внешнего контура; он общий для глифа.
            n1 = (handed*incoming[1], -handed*incoming[0])
            n2 = (handed*outgoing[1], -handed*outgoing[0])
            bisector = _unit(n1[0]+n2[0], n1[1]+n2[1])
            if bisector is None:
                continue
            cosine = bisector[0]*n1[0] + bisector[1]*n1[1]
            if cosine < 0.10:
                continue
            # Ограничиваем митер на острых углах, чтобы избежать игл.
            displacement = shift * min(1.8, 1.0/cosine)
            xy = (round(current[0]+bisector[0]*displacement),
                  round(current[1]+bisector[1]*displacement))
            if xy != current:
                updates[idx] = xy
                contour_moved = True
                moved_points += 1
        changed += int(contour_moved)
    for i, xy in updates.items():
        coords[i] = xy
    if stats is not None:
        stats["shift_units"] = round(shift, 2)
        stats["changed_points"] = moved_points
        stats["changed_contours"] = changed
    return changed


def round_corners(glyph, roundness: float, em: int = 1000,
                  stats: dict | None = None) -> int:
    """Заменить резкие углы между прямыми участками квадратичными дугами.

    Только вершины, соседние точки которых лежат НА контуре; off-curve
    контрольные точки уже существующих кривых не изменяем.
    """
    if type(roundness) not in (int, float) or not math.isfinite(roundness) or not 0 <= roundness <= .45:
        raise ValueError("corner_roundness: допустимо 0..0.45")
    if roundness <= 0 or glyph.numberOfContours <= 0:
        return 0

    coordinates = glyph.coordinates
    flags = glyph.flags
    fresh_points = []
    fresh_flags = []
    ends = []
    count_rounded = 0
    start = 0
    for end in glyph.endPtsOfContours:
        indices = list(range(start, end+1))
        n = len(indices)
        for j, index in enumerate(indices):
            x, y = coordinates[index]
            prev_index = indices[(j-1) % n]
            next_index = indices[(j+1) % n]
            if n < 3 or not (flags[index] & 1) or not (flags[prev_index] & 1) or not (flags[next_index] & 1):
                fresh_points.append((x,y)); fresh_flags.append(flags[index]&1)
                continue
            px, py = coordinates[prev_index]
            nx, ny = coordinates[next_index]
            u = _unit(px-x, py-y)
            v = _unit(nx-x, ny-y)
            if u is None or v is None:
                fresh_points.append((x,y)); fresh_flags.append(1)
                continue
            interior_cos = max(-1., min(1., u[0]*v[0]+u[1]*v[1]))
            # Почти 180° = прямая; округляем только настоящие углы.
            angle = math.degrees(math.acos(interior_cos))
            if not (30 < angle < 165):
                fresh_points.append((x,y)); fresh_flags.append(1)
                continue
            l1=math.hypot(px-x, py-y); l2=math.hypot(nx-x, ny-y)
            # Радиус в единицах em, но никогда не откусываем весь короткий штрих.
            radius = min(em*roundness*.13, .28*l1, .28*l2)
            if radius < 2.0:
                fresh_points.append((x,y)); fresh_flags.append(1)
                continue
            p_in = (round(x + u[0]*radius), round(y + u[1]*radius))
            p_out = (round(x + v[0]*radius), round(y + v[1]*radius))
            if p_in == (x,y) or p_out == (x,y) or p_in == p_out:
                fresh_points.append((x,y)); fresh_flags.append(1)
                continue
            # Три точки в TrueType: линия до p_in -> quadratic с контрольной
            # original vertex -> p_out -> следующая линия. Реальная дуга.
            fresh_points.extend([p_in, (x,y), p_out])
            fresh_flags.extend([1, 0, 1])
            count_rounded += 1
        if n:
            ends.append(len(fresh_points)-1)
        start = end+1
    if count_rounded:
        glyph.coordinates = GlyphCoordinates(fresh_points)
        glyph.flags = bytearray(fresh_flags)
        glyph.endPtsOfContours = ends
        glyph.numberOfContours = len(ends)
    if stats is not None:
        stats["rounded_corners"] = count_rounded
    return count_rounded
