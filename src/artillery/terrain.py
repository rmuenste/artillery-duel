from pathlib import Path

import numpy as np
import pygame

from . import scaling

TERRAIN_COLOR = np.array([64, 64, 64], dtype=np.uint8)    # dark grey
SKY_COLOR = np.array([135, 206, 235], dtype=np.uint8)      # light blue

_TEXTURE_PATH = Path(__file__).parent / "assets" / "images" / "texture_mountain.jpg"

# Loaded once, then reused across Terrain instances at the same resolution.
_texture_cache: dict[tuple[int, int], np.ndarray] = {}


def _load_texture(width: int, height: int) -> np.ndarray:
    """Load and scale the mountain texture to (height, width, 3) uint8 array."""
    key = (width, height)
    if key in _texture_cache:
        return _texture_cache[key]
    surf = pygame.image.load(_TEXTURE_PATH)
    surf = pygame.transform.smoothscale(surf, (width, height))
    # surfarray gives (width, height, 3) — transpose to (height, width, 3)
    arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.uint8)
    _texture_cache[key] = arr
    return arr


class Terrain:

    @property
    def WIDTH(self) -> int:
        return scaling.width

    @property
    def HEIGHT(self) -> int:
        return scaling.height

    def __init__(self, seed: int | None = None, roughness: float = 0.6) -> None:
        if seed is None:
            seed = int(np.random.randint(0, 2**31))
        self.seed = seed
        self.roughness = roughness
        self._rng = np.random.default_rng(seed)

        self._width = scaling.width
        self._height = scaling.height
        self._scale = scaling.scale
        self._platform_width = round(80 * self._scale)

        self.heights = self._generate_heights()
        self.platforms = self._place_platforms()
        self.pixels = self._build_pixel_array()

    # ------------------------------------------------------------------ #
    # Generation                                                           #
    # ------------------------------------------------------------------ #

    def _generate_heights(self) -> np.ndarray:
        """Return a 1-D int array of surface y-positions (one per column).

        y=0 is the top of the screen; larger y values are lower on screen.
        """
        w, h = self._width, self._height
        heights = np.zeros(w, dtype=float)

        mid_y = h * 0.55
        heights[0] = mid_y + self._rng.uniform(-1, 1) * h * 0.15
        heights[-1] = mid_y + self._rng.uniform(-1, 1) * h * 0.15

        self._displace(heights, 0, w - 1, h * 0.35)

        heights = np.clip(heights, h * 0.15, h * 0.88)
        return heights.astype(int)

    def _displace(self, heights: np.ndarray, lo: int, hi: int, scale: float) -> None:
        """Recursive 1-D midpoint displacement."""
        if hi - lo <= 1:
            return
        mid = (lo + hi) // 2
        heights[mid] = (
            (heights[lo] + heights[hi]) / 2.0
            + self._rng.uniform(-1, 1) * scale
        )
        next_scale = scale * (2.0 ** -self.roughness)
        self._displace(heights, lo, mid, next_scale)
        self._displace(heights, mid, hi, next_scale)

    def _place_platforms(self) -> list[tuple[int, int]]:
        """Carve two flat platforms into heights.

        Returns [(center_x, surface_y), ...].  Each platform spans
        center_x - half .. center_x + half.
        """
        w = self._width
        half = self._platform_width // 2

        left_zone = (0, round(w * 0.15))
        right_zone = (round(w * 0.85), w)

        platforms = []
        for zone_start, zone_end in (left_zone, right_zone):
            cx = int(self._rng.integers(zone_start + half, zone_end - half + 1))
            y  = int(self.heights[cx])
            self.heights[cx - half : cx + half] = y
            platforms.append((cx, y))
        return platforms

    # ------------------------------------------------------------------ #
    # Pixel array                                                          #
    # ------------------------------------------------------------------ #

    def _build_pixel_array(self) -> np.ndarray:
        """Return bool array shape (HEIGHT, WIDTH); True = solid terrain."""
        y_idx = np.arange(self._height)[:, np.newaxis]
        return y_idx >= self.heights[np.newaxis, :]

    def carve_crater(self, cx: int, cy: int, radius: int) -> None:
        """Remove terrain in a circle around (cx, cy).

        Sets pixels to False (sky) and lowers heights accordingly.
        Call to_surface_array() again afterwards to get the updated image.
        """
        w, h = self._width, self._height
        y_lo = max(0, cy - radius)
        y_hi = min(h, cy + radius + 1)
        x_lo = max(0, cx - radius)
        x_hi = min(w, cx + radius + 1)

        ys = np.arange(y_lo, y_hi)[:, np.newaxis]
        xs = np.arange(x_lo, x_hi)[np.newaxis, :]
        dist_sq = (xs - cx) ** 2 + (ys - cy) ** 2
        inside = dist_sq <= radius * radius

        self.pixels[y_lo:y_hi, x_lo:x_hi] &= ~inside

        # Recompute heights for affected columns
        for x in range(x_lo, x_hi):
            col = self.pixels[:, x]
            solid = np.nonzero(col)[0]
            self.heights[x] = solid[0] if len(solid) > 0 else h

    def to_surface_array(self, background: np.ndarray | None = None) -> np.ndarray:
        """Return uint8 RGB array of shape (WIDTH, HEIGHT, 3) for pygame surfarray.

        The mountain texture is vertically aligned so that its top row
        maps to the highest terrain point — snow caps land on the peaks.

        background: optional (HEIGHT, WIDTH, 3) uint8 array used in place of
                    SKY_COLOR for sky pixels.
        """
        w, h = self._width, self._height
        min_y = int(self.heights.min())
        max_y = h  # terrain extends to the bottom of the screen

        # Scale texture to cover only the terrain vertical span
        terrain_span = max_y - min_y
        if terrain_span < 1:
            terrain_span = 1
        texture_strip = _load_texture(w, terrain_span)

        # Place the strip into a full-screen-height texture array
        texture_aligned = np.broadcast_to(SKY_COLOR, (h, w, 3)).copy()
        texture_aligned[min_y:max_y, :, :] = texture_strip

        # Mask: terrain pixels get texture, sky pixels get background or sky color
        mask = self.pixels[:, :, np.newaxis]  # (H, W, 1)
        sky = background if background is not None else np.broadcast_to(SKY_COLOR, (h, w, 3))
        rgb = np.where(mask, texture_aligned, sky)

        # surfarray expects (WIDTH, HEIGHT, 3)
        return rgb.transpose(1, 0, 2).astype(np.uint8)
