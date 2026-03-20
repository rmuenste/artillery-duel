from __future__ import annotations

import math

import pygame

from . import scaling

# ------------------------------------------------------------------ #
# Tunable layout constants                                             #
# ------------------------------------------------------------------ #

# Base value at 600p — scaled at runtime via scaling.scale
_BASE_BODY_Y_OFFSET: int = 22

# Angle (degrees above horizontal) that the barrel points in the
# source image before any aim rotation is applied.
BARREL_NATURAL_ANGLE: float = 1.5

# Barrel attachment point on the body image (relative coords, 0-1).
TURRET_ON_BODY: tuple[float, float] = (0.50, 0.45)

# Pivot point on the barrel image — the breech end (unflipped).
BREECH_ON_BARREL: tuple[float, float] = (0.66, 0.50)


# ------------------------------------------------------------------ #
# Rotation helper                                                      #
# ------------------------------------------------------------------ #

def _blit_rotated(
    screen: pygame.Surface,
    surf: pygame.Surface,
    pivot_screen: tuple[int, int],
    pivot_local: tuple[float, float],
    angle: float,
) -> None:
    """Rotate *surf* by *angle* degrees CCW, keeping *pivot_local* pinned
    at *pivot_screen*.

    **The Ruler Analogy**
    You pinch a ruler at the 0 cm mark (``pivot_local`` — the breech).
    The centre of the ruler is at the 15 cm mark (the image centre).
    Swing the ruler by ``angle`` degrees — the 15 cm mark traces an arc.
    Wherever it lands is where Pygame must place the rotated image centre.
    """
    # 1. The ruler: vector from pivot (our fingers) to image centre.
    pivot = pygame.math.Vector2(pivot_local)
    image_centre = pygame.math.Vector2(surf.get_rect().center)
    pivot_to_centre = image_centre - pivot

    # 2. Swing the ruler by the same rotation that transform.rotate applies.
    #    transform.rotate(angle) is visually CCW on screen.
    #    Vector2.rotate(angle) is standard-math CCW (= visually CW on screen).
    #    → negate the angle so the vector swings the same way as the image.
    swung = pivot_to_centre.rotate(-angle)

    # 3. The image centre must land here so the pivot stays fixed.
    new_centre = pygame.math.Vector2(pivot_screen) + swung

    # 4. Create the rotated surface and place its centre.
    rotated = pygame.transform.rotate(surf, angle)
    rect = rotated.get_rect(center=(round(new_centre.x), round(new_centre.y)))
    screen.blit(rotated, rect)


# ------------------------------------------------------------------ #
# Tank                                                                 #
# ------------------------------------------------------------------ #

class Tank:
    """Two-sprite tank: a static body and a rotating barrel.

    facing="left"  → fires left  (right-side player, source image orientation)
    facing="right" → fires right (left-side player, body/barrel flipped)
    """

    MAX_HITS: int = 4

    def __init__(
        self,
        body_surf: pygame.Surface,
        barrel_surf: pygame.Surface,
        cx: int,
        sy: int,
        facing: str,
        damage_surfs: list[pygame.Surface] | None = None,
    ) -> None:
        self.cx = cx
        self.sy = sy
        self.facing = facing
        self.aim_angle: float = 45.0   # degrees above horizontal
        self.power: float = 0.5        # normalised 0..1 (mid = default)
        self.hits: int = 0

        if facing == "right":
            body_surf   = pygame.transform.flip(body_surf,   True, False)
            barrel_surf = pygame.transform.flip(barrel_surf, True, False)
            damage_surfs = [pygame.transform.flip(s, True, False) for s in (damage_surfs or [])]
        else:
            damage_surfs = list(damage_surfs or [])

        self.body   = body_surf
        self.barrel = barrel_surf
        self._damage_surfs: list[pygame.Surface] = damage_surfs

        # Breech pivot on the (possibly flipped) barrel surface — keep as float
        # so the sub-pixel position doesn't trace a circle when rotated.
        self._breech_local: tuple[float, float] = (0.0, 0.0)
        self._update_breech_local()

    @property
    def destroyed(self) -> bool:
        return self.hits >= self.MAX_HITS

    @property
    def _current_body(self) -> pygame.Surface:
        if self.hits == 0 or not self._damage_surfs:
            return self.body
        idx = min(self.hits - 1, len(self._damage_surfs) - 1)
        return self._damage_surfs[idx]

    def register_hit(self) -> None:
        """Record a hit on this tank (capped at MAX_HITS)."""
        self.hits = min(self.hits + 1, self.MAX_HITS)

    def _update_breech_local(self) -> None:
        """Recompute _breech_local from the current BREECH_ON_BARREL constant.
        Call this after changing BREECH_ON_BARREL at runtime."""
        bw, bh = self.barrel.get_size()
        breech_x_frac = (1.0 - BREECH_ON_BARREL[0]) if self.facing == "right" else BREECH_ON_BARREL[0]
        self._breech_local = (
            bw * breech_x_frac,
            bh * BREECH_ON_BARREL[1],
        )

    def turret_screen_pos(self) -> tuple[int, int]:
        """Turret attachment point in screen coordinates."""
        bw, bh = self.body.get_size()
        body_x = self.cx - bw // 2
        body_y = self.sy - bh + round(_BASE_BODY_Y_OFFSET * scaling.scale)
        return (
            body_x + int(bw * TURRET_ON_BODY[0]),
            body_y + int(bh * TURRET_ON_BODY[1]),
        )

    def muzzle_pos(self) -> tuple[float, float]:
        """Barrel tip (muzzle) in screen coordinates."""
        tx, ty = self.turret_screen_pos()
        bw, bh = self.barrel.get_size()

        # Muzzle is the opposite end of the barrel from the breech.
        # For the unflipped barrel (facing="left"), muzzle is at x=0.
        # For flipped (facing="right"), muzzle is at x=bw.
        if self.facing == "right":
            muzzle_local = (bw, bh * 0.5)
        else:
            muzzle_local = (0.0, bh * 0.5)

        # Vector from breech to muzzle in the barrel's local space
        breech_to_muzzle = pygame.math.Vector2(
            muzzle_local[0] - self._breech_local[0],
            muzzle_local[1] - self._breech_local[1],
        )

        # Rotate by the same pygame angle used for drawing
        if self.facing == "left":
            pygame_angle = BARREL_NATURAL_ANGLE - self.aim_angle
        else:
            pygame_angle = self.aim_angle - BARREL_NATURAL_ANGLE

        rotated = breech_to_muzzle.rotate(-pygame_angle)
        return (tx + rotated.x, ty + rotated.y)

    def body_rect(self) -> pygame.Rect:
        """Axis-aligned bounding rect of the tank body in screen coordinates."""
        bw, bh = self.body.get_size()
        body_x = self.cx - bw // 2
        body_y = self.sy - bh + round(_BASE_BODY_Y_OFFSET * scaling.scale)
        return pygame.Rect(body_x, body_y, bw, bh)

    def hit_test(self, sx: int, sy: int) -> bool:
        """Return True if screen point (sx, sy) hits a non-transparent body pixel."""
        if self.destroyed:
            return False
        rect = self.body_rect()
        if not rect.collidepoint(sx, sy):
            return False
        local_x = sx - rect.x
        local_y = sy - rect.y
        alpha = self._current_body.get_at((local_x, local_y)).a
        return alpha > 0

    def draw(
        self,
        screen: pygame.Surface,
        show_turret_dot: bool = False,
        show_barrel_debug: bool = False,
    ) -> None:
        bw, bh = self.body.get_size()
        body_x = self.cx - bw // 2
        body_y = self.sy - bh + round(_BASE_BODY_Y_OFFSET * scaling.scale)

        screen.blit(self._current_body, (body_x, body_y))

        if self.destroyed:
            return

        turret = self.turret_screen_pos()

        if self.facing == "left":
            pygame_angle = BARREL_NATURAL_ANGLE - self.aim_angle
        else:
            pygame_angle = self.aim_angle - BARREL_NATURAL_ANGLE

        _blit_rotated(screen, self.barrel, turret, self._breech_local, pygame_angle)

        if show_turret_dot:
            # Red circle — should stay perfectly still as barrel rotates
            pygame.draw.circle(screen, (255, 0, 0), turret, 5, 2)

        if show_barrel_debug:
            _draw_barrel_debug(screen, self.barrel, self._breech_local, pygame_angle)


# ------------------------------------------------------------------ #
# Debug helpers                                                        #
# ------------------------------------------------------------------ #

# Top-right corner: isolated barrel view + breech marker
def _debug_pos() -> tuple[int, int]:
    return (scaling.width - round(170 * scaling.scale), 10)


def _draw_barrel_debug(
    screen: pygame.Surface,
    barrel: pygame.Surface,
    breech_local: tuple[float, float],
    angle: float,
) -> None:
    """Draw the rotated barrel at a fixed screen position and mark the
    computed breech point with a green circle so the user can judge
    whether BREECH_ON_BARREL matches the actual pixel."""

    pos = _debug_pos()
    rotated = pygame.transform.rotate(barrel, angle)
    rw, rh = rotated.get_size()

    # Dark background so the barrel is readable against any terrain
    bg = pygame.Surface((rw, rh), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 160))
    screen.blit(bg, pos)
    screen.blit(rotated, pos)

    # Where does breech_local land inside the rotated surface?
    bw, bh = barrel.get_size()
    offset = pygame.math.Vector2(
        breech_local[0] - bw // 2,
        breech_local[1] - bh // 2,
    )
    rotated_offset = offset.rotate(-angle)
    breech_screen = (
        pos[0] + rw // 2 + round(rotated_offset.x),
        pos[1] + rh // 2 + round(rotated_offset.y),
    )
    pygame.draw.circle(screen, (0, 255, 0), breech_screen, 5, 2)
