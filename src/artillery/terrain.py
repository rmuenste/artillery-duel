import numpy as np

TERRAIN_COLOR = np.array([64, 64, 64], dtype=np.uint8)    # dark grey
SKY_COLOR = np.array([135, 206, 235], dtype=np.uint8)      # light blue


PLATFORM_WIDTH = 40
LEFT_ZONE  = (0, 120)    # x range reserved for the left tank
RIGHT_ZONE = (680, 800)  # x range reserved for the right tank


class Terrain:
    WIDTH = 800
    HEIGHT = 600

    def __init__(self, seed: int | None = None, roughness: float = 0.6) -> None:
        if seed is None:
            seed = int(np.random.randint(0, 2**31))
        self.seed = seed
        self.roughness = roughness
        self._rng = np.random.default_rng(seed)
        self.heights = self._generate_heights()
        self.platforms = self._place_platforms()  # [(x_left, surface_y), ...]
        self.pixels = self._build_pixel_array()

    # ------------------------------------------------------------------ #
    # Generation                                                           #
    # ------------------------------------------------------------------ #

    def _generate_heights(self) -> np.ndarray:
        """Return a 1-D int array of surface y-positions (one per column).

        y=0 is the top of the screen; larger y values are lower on screen.
        """
        heights = np.zeros(self.WIDTH, dtype=float)

        mid_y = self.HEIGHT * 0.55
        heights[0] = mid_y + self._rng.uniform(-1, 1) * self.HEIGHT * 0.15
        heights[-1] = mid_y + self._rng.uniform(-1, 1) * self.HEIGHT * 0.15

        self._displace(heights, 0, self.WIDTH - 1, self.HEIGHT * 0.35)

        heights = np.clip(heights, self.HEIGHT * 0.15, self.HEIGHT * 0.88)
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
        center_x-20 .. center_x+20 (PLATFORM_WIDTH = 40).
        """
        half = PLATFORM_WIDTH // 2
        platforms = []
        for zone_start, zone_end in (LEFT_ZONE, RIGHT_ZONE):
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
        y_idx = np.arange(self.HEIGHT)[:, np.newaxis]   # (HEIGHT, 1)
        return y_idx >= self.heights[np.newaxis, :]      # (HEIGHT, WIDTH)

    def to_surface_array(self) -> np.ndarray:
        """Return uint8 RGB array of shape (WIDTH, HEIGHT, 3) for pygame surfarray."""
        mask = self.pixels.T  # (WIDTH, HEIGHT)
        rgb = np.where(mask[:, :, np.newaxis], TERRAIN_COLOR, SKY_COLOR)
        return rgb.astype(np.uint8)
