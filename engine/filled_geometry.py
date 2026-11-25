"""Bounded GEOS vector fallback for decorative TrueType outlines (non-zero fill).

Only the fallback uses polygonal approximations; original quadratic outlines
remain intact when the regular algorithms succeed or no effect is possible.
"""
from __future__ import annotations
import math
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.pens.ttGlyphPen import TTGlyphPen

MAX_INPUT_POINTS = 12000
MAX_SEGMENTS = 24000
MAX_FACES = 2500
MAX_OUTPUT_POINTS = 28000

class _Pen(BasePen):
    def __init__(self, tolerance):
        super().__init__(None)
        self.tolerance = tolerance
        self.rings = []
        self.points = []
    def _moveTo(self, p): self.points = [tuple(p)]
    def _lineTo(self, p): self.points.append(tuple(p))
    def _qCurveToOne(self, c, p):
        a = self._getCurrentPoint()
        # Uniform quadratic subdivision: max chord error <= |a-2c+p|/(4*n²).
        n = max(1, math.ceil(math.sqrt(math.hypot(a[0]-2*c[0]+p[0], a[1]-2*c[1]+p[1])/(4*self.tolerance))))
        for i in range(1, n+1):
            t = i/n; s = 1-t
            self.points.append((s*s*a[0]+2*s*t*c[0]+t*t*p[0], s*s*a[1]+2*s*t*c[1]+t*t*p[1]))
    def _closePath(self):
        if len(self.points) >= 3:
            if self.points[0] != self.points[-1]: self.points.append(self.points[0])
            self.rings.append(self.points)
        self.points = []
    def _endPath(self): self._closePath()


def polygons(geom):
    if geom.is_empty: return []
    if geom.geom_type == 'Polygon': return [geom]
    if hasattr(geom, 'geoms'):
        return [p for g in geom.geoms for p in polygons(g)]
    return []


def filled_region(glyph, em):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union, polygonize
    if len(glyph.coordinates) > MAX_INPUT_POINTS: raise ValueError('input limit')
    pen = _Pen(max(.35, em*.00045)); glyph.draw(pen, None)
    rings = pen.rings
    if sum(map(len, rings)) > MAX_SEGMENTS: raise ValueError('segment limit')
    if not rings: return Polygon()
    if len(rings) == 1:
        p = Polygon(rings[0])
        if p.is_valid: return p
    # Node intersecting strokes, then select faces by TrueType non-zero winding,
    # not even-odd (overlapping brush strokes must remain ink).
    faces = list(polygonize(unary_union([LineString(r) for r in rings])))
    if len(faces) > MAX_FACES: raise ValueError('face limit')
    if not faces: return Polygon()
    a = np.concatenate([np.asarray(r[:-1], dtype=float) for r in rings]); b = np.concatenate([np.asarray(r[1:], dtype=float) for r in rings])
    ax, ay = a.T; bx, by = b.T
    picked = []
    for face in faces:
        pt = face.representative_point(); x, y = pt.x, pt.y
        up = (ay <= y) & (by > y); down = (by <= y) & (ay > y)
        cross = (bx-ax)*(y-ay)-(by-ay)*(x-ax)
        if np.count_nonzero(up & (cross > 0)) != np.count_nonzero(down & (cross < 0)):
            picked.append(face)
    return unary_union(picked) if picked else Polygon()


def _write(glyph, geom, em):
    from shapely import set_precision
    from shapely.geometry.polygon import orient
    geom = set_precision(geom.simplify(max(.25, em*.00025), preserve_topology=True), 1.0)
    if geom.is_empty or not geom.is_valid: return False
    pen = TTGlyphPen(None); count = 0
    for p in polygons(geom):
        p = orient(p, sign=-1.0)
        for r in [p.exterior, *p.interiors]:
            pts = list(r.coords)[:-1]
            if len(pts) < 3: continue
            count += len(pts)
            if count > MAX_OUTPUT_POINTS: return False
            pen.moveTo(pts[0])
            for pt in pts[1:]: pen.lineTo(pt)
            pen.closePath()
    if not count: return False
    result = pen.glyph()
    glyph.__dict__.clear(); glyph.__dict__.update(result.__dict__)
    return True


def change_filled_weight(glyph, scale, em, stats):
    """Offset the filled shape, with an adaptive cap for fragile strokes."""
    try:
        ink = filled_region(glyph, em)
        if ink.is_empty: return 0
        # Effective thickness (2*area/perimeter), so thin decorative outlines
        # do not disappear or become solid blocks at the end of the slider.
        thickness = 2*ink.area/max(ink.length, 1)
        shift = math.copysign(min(abs(scale-1)*em*.11, abs(scale-1)*thickness*.85), scale-1)
        from shapely.ops import unary_union
        parts = polygons(ink)
        changed_parts = []
        for p in parts:
            d = shift
            for _ in range(6):
                q = p.buffer(d, quad_segs=4, join_style=2, mitre_limit=1.8)
                # Keep each original connected component in thinning mode,
                # and prevent major holes from disappearing in thickening.
                if not q.is_empty and q.area >= p.area*.48 and (d > 0 or len(polygons(q)) == 1):
                    if d < 0 or all(q.intersection(h).area < h.area*.85 for h in _major_holes(p, em)):
                        break
                d *= .5
            else:
                q = p
            changed_parts.append(q)
        out = unary_union(changed_parts)
        if abs(out.area-ink.area) < max(1, ink.area*.001): return 0
        if not _write(glyph, out, em): return 0
        stats['filled_geometry'] = True
        return glyph.numberOfContours
    except Exception as exc:
        stats['fallback_error'] = str(exc)
        return 0


def _major_holes(p, em):
    from shapely.geometry import Polygon
    return [h for r in p.interiors if (h := Polygon(r)).area >= (em*.012)**2]


def change_filled_counters(glyph, scale, em, stats, _attempt=0):
    """Edit enclosed white regions, including holes formed by overlapping ink."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    try:
        ink = filled_region(glyph, em)
        parts = polygons(ink)
        stats['contours_total'] = glyph.numberOfContours
        holes = [(p, h) for p in parts for h in _major_holes(p, em)]
        stats['holes_found'] = len(holes)
        if not holes:
            stats['skip_reason'] = 'нет замкнутого просвета в залитой области'
            return 0
        additions = []; removals = []; factors = []
        for p, h in holes:
            # Convert scale to an approximate normal offset, then constrain
            # it locally so thin strokes and neighbouring counters survive.
            radius = 2*h.area/max(h.length, 1)
            thickness = 2*p.area/max(p.length, 1)
            # Outline lettering can have two neighbouring white areas on opposite
            # sides of a very thin stroke. Limit both boundaries more strongly.
            limit = .65 if thickness < em*.045 else 1.8
            d = min(abs(scale-1)*radius, abs(scale-1)*thickness*limit)
            if d < .45: continue
            if scale > 1:
                shell = Polygon(p.exterior)
                margin = max(1.0, min(em*.012, thickness*.65))
                other = [Polygon(r) for r in p.interiors if not Polygon(r).equals(h)]
                safe = shell.buffer(-margin, quad_segs=3)
                if other:
                    safe = safe.difference(unary_union([x.buffer(margin, quad_segs=3) for x in other]))
                expanded = h.buffer(d, quad_segs=4, join_style=2, mitre_limit=1.8).intersection(safe).union(h)
                delta = expanded.difference(h).intersection(p)
                if delta.area < max(1, h.area*.002): continue
                removals.append(delta); ratio = math.sqrt(1+delta.area/h.area)
            else:
                smaller = h.buffer(-d, quad_segs=4, join_style=2, mitre_limit=1.8)
                if smaller.is_empty or len(polygons(smaller)) != 1 or smaller.area < h.area*.45:
                    continue
                delta = h.difference(smaller).difference(ink)
                if delta.area < max(1, h.area*.002): continue
                additions.append(delta); ratio = math.sqrt(1-delta.area/h.area)
            factors.append(ratio)
        if not factors:
            stats['limited'] = len(holes); stats['skipped'] = len(holes)
            stats['effective_scale'] = 1.0
            return 0
        out = ink.union(unary_union(additions)) if additions else ink.difference(unary_union(removals))
        # If simultaneous expansion would cut a stroke or merge enclosed areas,
        # decline the change instead of emitting damaged lettering.
        result_parts = polygons(out)
        if len(result_parts) != len(parts):
            if _attempt < 3:
                count = change_filled_counters(glyph, 1+(scale-1)*.5, em, stats, _attempt+1)
                if count:
                    stats['limited'] = max(stats.get('limited', 0), len(holes))
                    return count
            stats.update(limited=len(holes), skipped=len(holes), effective_scale=1.0,
                         skip_reason='изменение нарушает связность штрихов')
            return 0
        if not _write(glyph, out, em): return 0
        stats.update(filled_geometry=True, recovery_used=True, complexity_skipped=False,
                     effective_scale=round(sum(factors)/len(factors), 4),
                     limited=sum(abs(f-scale)>.002 for f in factors),
                     skipped=len(holes)-len(factors), skip_reason='')
        return len(factors)
    except Exception as exc:
        stats['fallback_error'] = str(exc)
        stats['skip_reason'] = 'ошибка обработки залитой области'
        return 0
