from __future__ import annotations

import pygame

# ------------------------------------------------------------------ #
# Tunable layout constants                                             #
# ------------------------------------------------------------------ #

# Shifts body downward so the tracks sit on the platform surface.
# Accounts for transparent padding at the top of the tank image.
BODY_Y_OFFSET: int = 22

# Angle (degrees above horizontal) that the barrel points in the
# source image before any aim rotation is applied.
BARREL_NATURAL_ANGLE: float = 45.85

# Barrel attachment point on the body image (relative coords, 0-1).
TURRET_ON_BODY: tuple[float, float] = (0.50, 0.35)

# Pivot point on the barrel image — the breech end (unflipped).
BREECH_ON_BARREL: tuple[float, float] = (0.66, 0.4)


# ------------------------------------------------------------------ #
# Rotation helper                                                      #
# ------------------------------------------------------------------ #

def _blit_rotated(
    screen: pygame.Surface,
    surf: pygame.Surface,
    pivot_screen: tuple[int, int],
    pivot_local: tuple[int, int],
    angle: float,
) -> None:
    """Rotate *surf* by *angle* degrees CCW and blit it so that
    *pivot_local* (surface coords) stays fixed at *pivot_screen* (screen coords).
    """
    # Offset from surface centre to pivot (integer centre, matching get_rect)
    w, h = surf.get_size()
    offset = pygame.math.Vector2(pivot_local[0] - w // 2,
                                  pivot_local[1] - h // 2)

    # Rotate that offset the same way transform.rotate moves pixels.
    # transform.rotate is visually CCW; Vector2.rotate is visually CW → negate.
    rotated_offset = offset.rotate(-angle)

    rotated = pygame.transform.rotate(surf, angle)
    # Position the rotated surface so the pivot lands at pivot_screen.
    center = pygame.math.Vector2(pivot_screen) - rotated_offset
    rect = rotated.get_rect(center=(round(center.x), round(center.y)))
    screen.blit(rotated, rect)


# ------------------------------------------------------------------ #
# Tank                                                                 #
# ------------------------------------------------------------------ #

class Tank:
    """Two-sprite tank: a static body and a rotating barrel.

    facing="left"  → fires left  (right-side player, source image orientation)
    facing="right" → fires right (left-side player, body/barrel flipped)
    """

    def __init__(
        self,
        body_surf: pygame.Surface,
        barrel_surf: pygame.Surface,
        cx: int,
        sy: int,
        facing: str,
    ) -> None:
        self.cx = cx
        self.sy = sy
        self.facing = facing
        self.aim_angle: float = 45.0   # degrees above horizontal

        if facing == "right":
            body_surf   = pygame.transform.flip(body_surf,   True, False)
            barrel_surf = pygame.transform.flip(barrel_surf, True, False)

        self.body   = body_surf
        self.barrel = barrel_surf

        # Breech pivot on the (possibly flipped) barrel surface
        bw, bh = self.barrel.get_size()
        breech_x_frac = (1.0 - BREECH_ON_BARREL[0]) if facing == "right" else BREECH_ON_BARREL[0]
        self._breech_local: tuple[int, int] = (
            int(bw * breech_x_frac),
            int(bh * BREECH_ON_BARREL[1]),
        )

    def draw(self, screen: pygame.Surface) -> None:
        bw, bh = self.body.get_size()
        body_x = self.cx - bw // 2
        body_y = self.sy - bh + BODY_Y_OFFSET

        screen.blit(self.body, (body_x, body_y))

        # Turret attachment point in screen space
        turret = (
            body_x + int(bw * TURRET_ON_BODY[0]),
            body_y + int(bh * TURRET_ON_BODY[1]),
        )

        # For facing="left" (unflipped, points upper-left at natural_angle):
        #   pygame_angle = natural_angle - aim_angle
        # For facing="right" (flipped, points upper-right at natural_angle):
        #   pygame_angle = aim_angle - natural_angle
        if self.facing == "left":
            pygame_angle = BARREL_NATURAL_ANGLE - self.aim_angle
        else:
            pygame_angle = self.aim_angle - BARREL_NATURAL_ANGLE

        _blit_rotated(screen, self.barrel, turret, self._breech_local, pygame_angle)
