"""Disposition des écrans dans un repère commun (pixels).

Deux écrans sont voisins sur un bord lorsque leurs rectangles se touchent (à
TOLERANCE px près) et se chevauchent sur ce bord. Le passage du curseur se fait
toujours vers le voisin déclaré par cette disposition.
"""

from dataclasses import asdict, dataclass

from .protocol import clamp

TOLERANCE = 2
SNAP_DISTANCE = 400


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


def _overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def _touches(a, b, side):
    """Vrai si `b` est collé à `a` sur `side`. Retourne aussi la longueur de contact."""
    if side == "right":
        touching = abs(b.x - (a.x + a.w)) <= TOLERANCE
        contact = _overlap(a.y, a.y + a.h, b.y, b.y + b.h)
    elif side == "left":
        touching = abs((b.x + b.w) - a.x) <= TOLERANCE
        contact = _overlap(a.y, a.y + a.h, b.y, b.y + b.h)
    elif side == "bottom":
        touching = abs(b.y - (a.y + a.h)) <= TOLERANCE
        contact = _overlap(a.x, a.x + a.w, b.x, b.x + b.w)
    else:  # top
        touching = abs((b.y + b.h) - a.y) <= TOLERANCE
        contact = _overlap(a.x, a.x + a.w, b.x, b.x + b.w)
    return touching and contact > 0, contact


def _intersects(a, b):
    return _overlap(a.x, a.x + a.w, b.x, b.x + b.w) > 0 and _overlap(
        a.y, a.y + a.h, b.y, b.y + b.h
    ) > 0


class Layout:
    def __init__(self, screens=None):
        self.screens = dict(screens or {})

    # --- Persistance -----------------------------------------------------

    def to_dict(self):
        return {name: asdict(rect) for name, rect in sorted(self.screens.items())}

    @classmethod
    def from_dict(cls, data):
        screens = {}
        for name, value in (data or {}).items():
            try:
                screens[str(name)] = Rect(
                    int(value["x"]), int(value["y"]), int(value["w"]), int(value["h"])
                )
            except (KeyError, TypeError, ValueError):
                continue  # entrée corrompue : on l'ignore
        return cls(screens)

    # --- Opérations ------------------------------------------------------

    def ensure(self, name, width, height, reference):
        """Crée l'écran s'il est inconnu (à droite de `reference`), sinon met à jour sa taille."""
        existing = self.screens.get(name)
        if existing is not None:
            existing.w, existing.h = int(width), int(height)
            return
        ref = self.screens.get(reference)
        if ref is None:
            self.screens[name] = Rect(0, 0, int(width), int(height))
            return
        candidates = [
            (ref.x + ref.w, ref.y),
            (ref.x - width, ref.y),
            (ref.x, ref.y + ref.h),
            (ref.x, ref.y - height),
        ]
        for x, y in candidates:
            rect = Rect(x, y, int(width), int(height))
            if not any(_intersects(rect, other) for other in self.screens.values()):
                self.screens[name] = rect
                return
        self.screens[name] = Rect(ref.x + ref.w, ref.y, int(width), int(height))

    def neighbor(self, name, side):
        """Nom de l'écran collé à `name` sur `side`, ou None."""
        rect = self.screens.get(name)
        if rect is None:
            return None
        best, best_contact = None, 0
        for other_name, other in sorted(self.screens.items()):
            if other_name == name:
                continue
            touching, contact = _touches(rect, other, side)
            if touching and contact > best_contact:
                best, best_contact = other_name, contact
        return best

    def snap(self, name, x, y):
        """Position (x, y) collée à un autre écran si elle est assez proche, sinon inchangée."""
        rect = self.screens.get(name)
        if rect is None:
            return x, y
        w, h = rect.w, rect.h
        best, best_distance = (x, y), None
        for other_name, other in self.screens.items():
            if other_name == name:
                continue
            candidates = [
                (other.x + other.w, clamp(y, other.y - h + 1, other.y + other.h - 1)),
                (other.x - w, clamp(y, other.y - h + 1, other.y + other.h - 1)),
                (clamp(x, other.x - w + 1, other.x + other.w - 1), other.y + other.h),
                (clamp(x, other.x - w + 1, other.x + other.w - 1), other.y - h),
            ]
            for cx, cy in candidates:
                distance = abs(cx - x) + abs(cy - y)
                if best_distance is None or distance < best_distance:
                    best, best_distance = (cx, cy), distance
        if best_distance is not None and best_distance <= SNAP_DISTANCE:
            return best
        return x, y

    def move(self, name, x, y):
        """Déplace l'écran `name` (position brute, sans snap)."""
        rect = self.screens[name]
        rect.x, rect.y = int(x), int(y)
