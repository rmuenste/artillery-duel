"""C64-inspired 'original' visual style for Artillery Duel."""

import numpy as np
import pygame

from . import scaling

SKY    = np.array([85,  85, 170], dtype=np.uint8)   # C64 blue
SAND   = np.array([196, 156,  68], dtype=np.uint8)  # sandy terrain
BROWN  = np.array([119,  68,  17], dtype=np.uint8)  # mountain fill
SNOW   = np.array([224, 224, 232], dtype=np.uint8)  # snow patches
TREE_L = (68, 136, 68)                               # light green
TREE_D = (34,  85, 34)                               # dark green
TRUNK  = (80,  40, 10)


def _displace(rng, heights: np.ndarray, lo: int, hi: int, scale: float, roughness: float = 0.4) -> None:
    """Recursive 1-D midpoint displacement."""
    if hi - lo <= 1:
        return
    mid = (lo + hi) // 2
    heights[mid] = (heights[lo] + heights[hi]) / 2.0 + rng.uniform(-1, 1) * scale
    next_scale = scale * (2.0 ** -roughness)
    _displace(rng, heights, lo, mid, next_scale, roughness)
    _displace(rng, heights, mid, hi, next_scale, roughness)


def make_mountain_surface(terrain) -> pygame.Surface:
    """Generate the non-destructible mountain backdrop as a pygame.Surface."""
    w, h = scaling.width, scaling.height
    rng = np.random.default_rng(terrain.seed ^ 0xDEAD)

    # Generate smooth mountain height profile
    mtn_heights = np.zeros(w, dtype=float)
    mid_y = h * 0.35
    mtn_heights[0]  = mid_y + rng.uniform(-1, 1) * h * 0.15
    mtn_heights[-1] = mid_y + rng.uniform(-1, 1) * h * 0.15
    _displace(rng, mtn_heights, 0, w - 1, h * 0.25)
    mtn_heights = np.clip(mtn_heights, h * 0.05, h * 0.65).astype(int)

    # Build RGB array (H, W, 3): SKY above profile, BROWN below
    rgb = np.full((h, w, 3), SKY, dtype=np.uint8)
    y_idx = np.arange(h)[:, np.newaxis]          # (H, 1)
    below_mtn = y_idx >= mtn_heights[np.newaxis, :]  # (H, W)
    rgb[below_mtn] = BROWN

    # Snow: vectorized — tallest peaks get snow caps
    raw_depth = np.maximum(0.0, (h * 0.35 - mtn_heights) * 0.6)
    depth = np.convolve(raw_depth, np.ones(15) / 15, mode='same')
    depth_int = depth.astype(int)
    peak_y   = mtn_heights[np.newaxis, :]   # (1, W)
    depth_2d = depth_int[np.newaxis, :]     # (1, W)
    snow_mask = (y_idx >= peak_y) & (y_idx < peak_y + depth_2d) & below_mtn
    rgb[snow_mask] = SNOW

    # surfarray expects (W, H, 3)
    return pygame.surfarray.make_surface(rgb.transpose(1, 0, 2))


def make_terrain_surface(terrain, mountain_surf: pygame.Surface) -> pygame.Surface:
    """Composite terrain over mountain backdrop and add pixel trees."""
    # Mountain backdrop as (H, W, 3)
    mtn_arr = pygame.surfarray.array3d(mountain_surf).transpose(1, 0, 2)

    # SAND where solid terrain, mountain where sky
    mask = terrain.pixels[:, :, np.newaxis]  # (H, W, 1)
    rgb = np.where(mask, SAND, mtn_arr).astype(np.uint8)

    surf = pygame.surfarray.make_surface(rgb.transpose(1, 0, 2))
    _draw_trees(surf, terrain)
    return surf


def _draw_pine(surf: pygame.Surface, x: int, y: int, size: int) -> None:
    """Draw a two-tier pixel pine tree. (x, y) is the base; size is total height."""
    trunk_h = max(2, size // 4)
    trunk_w = max(2, size // 6)
    t2_h    = size // 2
    t1_h    = max(2, size - t2_h - trunk_h)

    # Trunk
    pygame.draw.rect(surf, TRUNK, (x - trunk_w // 2, y - trunk_h, trunk_w, trunk_h))

    # Bottom tier
    t2_base = y - trunk_h
    t2_top  = t2_base - t2_h
    t2_hw   = size // 2
    pygame.draw.polygon(surf, TREE_D, [(x, t2_top), (x - t2_hw, t2_base), (x + t2_hw, t2_base)])
    i2_hw = t2_hw * 2 // 3
    pygame.draw.polygon(surf, TREE_L, [(x, t2_top + t2_h // 4), (x - i2_hw, t2_base), (x + i2_hw, t2_base)])

    # Top tier
    t1_base = t2_top + t2_h // 3
    t1_top  = t1_base - t1_h
    t1_hw   = t2_hw * 2 // 3
    pygame.draw.polygon(surf, TREE_D, [(x, t1_top), (x - t1_hw, t1_base), (x + t1_hw, t1_base)])
    i1_hw = t1_hw * 2 // 3
    pygame.draw.polygon(surf, TREE_L, [(x, t1_top + t1_h // 4), (x - i1_hw, t1_base), (x + i1_hw, t1_base)])


def _draw_trees(surf: pygame.Surface, terrain) -> None:
    """Scatter reproducible pixel pine trees across non-platform zones."""
    s = scaling.scale
    rng = np.random.default_rng(terrain.seed ^ 0xF00D)

    spacing   = round(40 * s)
    tree_size = round(12 * s)
    excl      = round(50 * s)
    platform_xs = [cx for cx, _ in terrain.platforms]
    w = scaling.width

    x = spacing // 2
    while x < w:
        near_platform = any(abs(x - px) < excl for px in platform_xs)
        jitter_x   = int(rng.integers(-spacing // 3, spacing // 3 + 1))
        size_jitter = int(rng.integers(-2, 3))
        if not near_platform:
            tx = max(0, min(w - 1, x + jitter_x))
            ty = int(terrain.heights[tx])
            size = max(6, tree_size + round(size_jitter * s))
            _draw_pine(surf, tx, ty, size)
        x += spacing
