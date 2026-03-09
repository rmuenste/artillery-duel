"""Projectile (shell) physics."""
from __future__ import annotations

import math

import pygame

from . import scaling

# Base values at 600p — scaled by scaling.scale
_BASE_GRAVITY: float = 500.0      # pixels/s²
_BASE_POWER_MIN: float = 100.0    # pixels/s
_BASE_POWER_MAX: float = 800.0    # pixels/s
_BASE_SHELL_RADIUS: int = 3


def gravity() -> float:
    return _BASE_GRAVITY * scaling.scale


def power_range() -> tuple[float, float]:
    s = scaling.scale
    return _BASE_POWER_MIN * s, _BASE_POWER_MAX * s


def power_from_normalised(t: float) -> float:
    """Convert normalised power (0..1) to pixels/s."""
    lo, hi = power_range()
    return lo + t * (hi - lo)


class Shell:
    """A single projectile in flight."""

    def __init__(self, x: float, y: float, vx: float, vy: float) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.alive = True

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @classmethod
    def fire(cls, tank: "tank_module_Tank", gravity_override: float | None = None) -> Shell:
        """Create a shell from *tank*'s current aim and power."""
        mx, my = tank.muzzle_pos()
        speed = power_from_normalised(tank.power)

        if tank.facing == "right":
            angle_rad = math.radians(tank.aim_angle)
        else:
            angle_rad = math.radians(180.0 - tank.aim_angle)

        vx = speed * math.cos(angle_rad)
        vy = -speed * math.sin(angle_rad)   # screen y is down
        return cls(mx, my, vx, vy)

    # ------------------------------------------------------------------ #
    # Simulation                                                           #
    # ------------------------------------------------------------------ #

    def update(self, dt_s: float, grav: float | None = None) -> None:
        if not self.alive:
            return
        g = grav if grav is not None else gravity()
        self.vy += g * dt_s
        self.x += self.vx * dt_s
        self.y += self.vy * dt_s

    def check_collision(
        self,
        terrain: "Terrain",
        tanks: list["Tank"],
        firing_tank_idx: int,
    ) -> str | None:
        """Check for collision.  Returns 'terrain', 'tank', 'offscreen', or None."""
        if not self.alive:
            return None

        ix, iy = int(self.x), int(self.y)

        # Off-screen sides / bottom
        if ix < 0 or ix >= scaling.width or iy >= scaling.height:
            self.alive = False
            return "offscreen"

        # Above screen — still in flight
        if iy < 0:
            return None

        # Terrain hit
        if terrain.pixels[iy, ix]:
            self.alive = False
            return "terrain"

        # Tank hit — pixel-perfect against non-transparent body pixels
        for i, tank in enumerate(tanks):
            if i == firing_tank_idx:
                continue
            if tank.hit_test(ix, iy):
                self.alive = False
                return "tank"

        return None

    # ------------------------------------------------------------------ #
    # Drawing                                                              #
    # ------------------------------------------------------------------ #

    def draw(self, screen: pygame.Surface) -> None:
        if not self.alive:
            return
        r = max(2, round(_BASE_SHELL_RADIUS * scaling.scale))
        pygame.draw.circle(screen, (255, 255, 255), (round(self.x), round(self.y)), r)
