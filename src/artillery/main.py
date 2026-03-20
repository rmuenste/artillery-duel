import argparse
import sys
from pathlib import Path

import pygame

from . import original_style
from . import scaling
from . import sounds
from .console import DebugConsole
from .shell import Shell, power_from_normalised
from . import shell as shell_module
from . import tank as tank_module
from .tank import Tank
from .terrain import Terrain

_IMAGES = Path(__file__).parent / "assets" / "images"
_BG_PATH = _IMAGES / "background_day.jpg"

# Background image array: (HEIGHT, WIDTH, 3) uint8, loaded once at startup.
_background: "np.ndarray | None" = None


def _load_background(width: int, height: int) -> "np.ndarray":
    import numpy as np
    surf = pygame.image.load(_BG_PATH).convert()
    surf = pygame.transform.smoothscale(surf, (width, height))
    # surfarray gives (W, H, 3) — transpose to (H, W, 3)
    return pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.uint8)

TOGGLE_KEY    = pygame.K_F12
ROTATION_SPEED = 60.0   # degrees per second
POWER_SPEED    = 0.5     # normalised units per second (0..1 range)
AIM_MIN, AIM_MAX = 0.0, 90.0

_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "600p":  (800,  600),
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
}


def _parse_resolution(value: str) -> tuple[int, int]:
    """Parse a resolution string: preset name or WxH."""
    if value in _RESOLUTION_PRESETS:
        return _RESOLUTION_PRESETS[value]
    if "x" in value:
        parts = value.split("x", 1)
        return int(parts[0]), int(parts[1])
    raise argparse.ArgumentTypeError(
        f"Unknown resolution '{value}'. Use a preset "
        f"({', '.join(_RESOLUTION_PRESETS)}) or WxH (e.g. 1024x768)."
    )


# --------------------------------------------------------------------------- #
# Mutable game state                                                           #
# --------------------------------------------------------------------------- #

_BASE_EXPLOSION_RADIUS: float = 20.0


class GameState:
    def __init__(self, body_surf: pygame.Surface, barrel_surf: pygame.Surface, damage_surfs: list[pygame.Surface], style: str = 'modern') -> None:
        self.roughness: float = 0.6
        self._body   = body_surf
        self._barrel = barrel_surf
        self._damage_surfs = damage_surfs
        self.style   = style
        self._mountain_surf: pygame.Surface | None = None
        self.terrain = Terrain(roughness=self.roughness)
        if self.style == 'original':
            self._mountain_surf = original_style.make_mountain_surface(self.terrain)
        self.surface = self._make_surface()
        self.tanks        = self._make_tanks()
        self.debug_pivot: bool = False
        self.active_tank: int = 0

        # Shell state
        self.shell: Shell | None = None
        self.firing_tank_idx: int = 0
        self.explosion_radius: float = _BASE_EXPLOSION_RADIUS * scaling.scale
        self.explosions: list[tuple[int, int, float, float]] = []  # (x, y, radius, timer)

    def regen(self, seed: int | None = None, roughness: float | None = None) -> None:
        if roughness is not None:
            self.roughness = roughness
        self.terrain = Terrain(seed=seed, roughness=self.roughness)
        if self.style == 'original':
            self._mountain_surf = original_style.make_mountain_surface(self.terrain)
        self.surface = self._make_surface()
        self.tanks   = self._make_tanks()
        self.shell = None
        self.explosions.clear()

    def _make_surface(self) -> pygame.Surface:
        if self.style == 'original':
            return original_style.make_terrain_surface(self.terrain, self._mountain_surf)
        return pygame.surfarray.make_surface(self.terrain.to_surface_array(_background))

    def _make_tanks(self) -> list[Tank]:
        (cx0, sy0), (cx1, sy1) = self.terrain.platforms
        return [
            Tank(self._body, self._barrel, cx0, sy0, facing="right", damage_surfs=self._damage_surfs),
            Tank(self._body, self._barrel, cx1, sy1, facing="left",  damage_surfs=self._damage_surfs),
        ]


# --------------------------------------------------------------------------- #
# Command registration                                                         #
# --------------------------------------------------------------------------- #

def _parse_seed_arg(args: list[str]) -> int | None:
    for arg in args:
        if arg.startswith("seed="):
            return int(arg.split("=", 1)[1])
    for arg in args:
        try:
            return int(arg)
        except ValueError:
            pass
    return None


def register_commands(console: DebugConsole, state: GameState) -> None:

    def cmd_regen(args: list[str]) -> str:
        seed = _parse_seed_arg(args)
        state.regen(seed=seed)
        return f"  seed={state.terrain.seed}  roughness={state.terrain.roughness}"

    def cmd_roughness(args: list[str]) -> str:
        if not args:
            return f"  roughness = {state.terrain.roughness}"
        value = float(args[0])
        if not 0.0 < value <= 2.0:
            return "  roughness must be in (0, 2]"
        state.regen(seed=state.terrain.seed, roughness=value)
        return f"  seed={state.terrain.seed}  roughness={state.terrain.roughness}"

    def cmd_seed(args: list[str]) -> str:
        return f"  seed = {state.terrain.seed}"

    def cmd_platforms(args: list[str]) -> str:
        half = round(20 * scaling.scale)
        lines = []
        for i, (cx, y) in enumerate(state.terrain.platforms):
            lines.append(f"  tank {i + 1}: center_x={cx}  x={cx - half}..{cx + half}  surface_y={y}")
        return "\n".join(lines)

    def cmd_debug_pivot(args: list[str]) -> str:
        state.debug_pivot = not state.debug_pivot
        return f"  debug_pivot {'ON' if state.debug_pivot else 'OFF'}"

    def cmd_turret(args: list[str]) -> str:
        if not args:
            x, y = tank_module.TURRET_ON_BODY
            return f"  TURRET_ON_BODY = ({x}, {y})"
        x, y = float(args[0]), float(args[1])
        tank_module.TURRET_ON_BODY = (x, y)
        return f"  TURRET_ON_BODY = ({x}, {y})"

    def cmd_breech(args: list[str]) -> str:
        if not args:
            x, y = tank_module.BREECH_ON_BARREL
            return f"  BREECH_ON_BARREL = ({x}, {y})"
        x, y = float(args[0]), float(args[1])
        tank_module.BREECH_ON_BARREL = (x, y)
        for tank in state.tanks:
            tank._update_breech_local()
        return f"  BREECH_ON_BARREL = ({x}, {y})"

    def cmd_aim(args: list[str]) -> str:
        tank = state.tanks[state.active_tank]
        if not args:
            return f"  aim = {tank.aim_angle:.2f}°"
        tank.aim_angle = max(AIM_MIN, min(AIM_MAX, float(args[0])))
        return f"  aim = {tank.aim_angle:.2f}°"

    def cmd_natural_angle(args: list[str]) -> str:
        if not args:
            return f"  BARREL_NATURAL_ANGLE = {tank_module.BARREL_NATURAL_ANGLE}"
        tank_module.BARREL_NATURAL_ANGLE = float(args[0])
        return f"  BARREL_NATURAL_ANGLE = {tank_module.BARREL_NATURAL_ANGLE}"

    def cmd_explosion_radius(args: list[str]) -> str:
        if not args:
            return f"  explosion_radius = {state.explosion_radius:.1f}"
        state.explosion_radius = float(args[0])
        return f"  explosion_radius = {state.explosion_radius:.1f}"

    def cmd_power(args: list[str]) -> str:
        tank = state.tanks[state.active_tank]
        if not args:
            speed = power_from_normalised(tank.power)
            return f"  power = {tank.power:.2f}  ({speed:.0f} px/s)"
        tank.power = max(0.0, min(1.0, float(args[0])))
        speed = power_from_normalised(tank.power)
        return f"  power = {tank.power:.2f}  ({speed:.0f} px/s)"

    def cmd_gravity(args: list[str]) -> str:
        if not args:
            return f"  gravity = {shell_module._BASE_GRAVITY} (scaled: {shell_module.gravity():.0f})"
        shell_module._BASE_GRAVITY = float(args[0])
        return f"  gravity = {shell_module._BASE_GRAVITY} (scaled: {shell_module.gravity():.0f})"

    console.register("regen",            cmd_regen)
    console.register("roughness",        cmd_roughness)
    console.register("seed",             cmd_seed)
    console.register("platforms",        cmd_platforms)
    console.register("debug_pivot",      cmd_debug_pivot)
    console.register("turret",           cmd_turret)
    console.register("breech",           cmd_breech)
    console.register("aim",              cmd_aim)
    console.register("natural_angle",    cmd_natural_angle)
    console.register("explosion_radius", cmd_explosion_radius)
    console.register("power",            cmd_power)
    def cmd_volume(args: list[str]) -> str:
        if not args:
            return f"  volume = {sounds._master_volume:.2f}"
        sounds.set_volume(float(args[0]))
        return f"  volume = {sounds._master_volume:.2f}"

    def cmd_style(args: list[str]) -> str:
        if not args:
            return f"  style = {state.style}"
        s = args[0]
        if s not in ("modern", "original"):
            return "  style must be 'modern' or 'original'"
        state.style = s
        if s == "original" and state._mountain_surf is None:
            state._mountain_surf = original_style.make_mountain_surface(state.terrain)
        state.surface = state._make_surface()
        return f"  style = {state.style}"

    console.register("gravity",          cmd_gravity)
    console.register("volume",           cmd_volume)
    console.register("style",            cmd_style)


# --------------------------------------------------------------------------- #
# Rendering helpers                                                            #
# --------------------------------------------------------------------------- #

def _draw_active_marker(screen: pygame.Surface, tank: Tank) -> None:
    """Draw a small downward-pointing triangle above the active tank."""
    s = scaling.scale
    bw, bh = tank.body.get_size()
    tip_x = tank.cx
    tip_y = tank.sy - bh + round(10 * s)
    half_w = round(6 * s)
    tri_h = round(10 * s)
    points = [
        (tip_x,          tip_y),
        (tip_x - half_w, tip_y - tri_h),
        (tip_x + half_w, tip_y - tri_h),
    ]
    pygame.draw.polygon(screen, (255, 255, 0), points)


def _power_color(t: float) -> tuple[int, int, int]:
    """Bipolar colormap: dark blue (0) → white (0.5) → dark red (1)."""
    if t < 0.5:
        f = t / 0.5  # 0..1 over the blue→white half
        r = round(20 + f * 235)
        g = round(20 + f * 235)
        b = round(140 + f * 115)
    else:
        f = (t - 0.5) / 0.5  # 0..1 over the white→red half
        r = round(255 - f * 115)
        g = round(255 - f * 235)
        b = round(255 - f * 235)
    return (r, g, b)


def _draw_power_indicator(screen: pygame.Surface, tank: Tank) -> None:
    """Vertical bar beside the active tank showing current power."""
    s = scaling.scale
    bar_w = round(6 * s)
    bar_h = round(50 * s)
    bw, bh = tank.body.get_size()

    # Position: to the right of a right-facing tank, left of a left-facing tank
    if tank.facing == "right":
        bar_x = tank.cx + bw // 2 + round(8 * s)
    else:
        bar_x = tank.cx - bw // 2 - round(8 * s) - bar_w

    bar_y = tank.sy - bh + round(10 * s)

    # Background
    pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))

    # Filled portion
    fill_h = round(bar_h * tank.power)
    fill_y = bar_y + bar_h - fill_h
    color = _power_color(tank.power)
    if fill_h > 0:
        pygame.draw.rect(screen, color, (bar_x, fill_y, bar_w, fill_h))

    # Border
    pygame.draw.rect(screen, (180, 180, 180), (bar_x, bar_y, bar_w, bar_h), 1)


_EXPLOSION_DURATION: float = 1.0  # seconds


def _draw_explosions(screen: pygame.Surface, explosions: list[tuple[int, int, float, float]]) -> None:
    for x, y, radius, timer in explosions:
        alpha = max(0, timer / _EXPLOSION_DURATION)
        color = (255, round(160 * alpha), 0)
        pygame.draw.circle(screen, color, (x, y), round(radius), 2)


# --------------------------------------------------------------------------- #
# Sprite loading                                                               #
# --------------------------------------------------------------------------- #

_BASE_BODY_SIZE = (120, 80)
_BASE_BARREL_SIZE = (120, 80)


def _load_and_scale_sprite(path: Path, base_size: tuple[int, int]) -> pygame.Surface:
    surf = pygame.image.load(path).convert_alpha()
    s = scaling.scale
    new_size = (round(base_size[0] * s), round(base_size[1] * s))
    if new_size != base_size:
        surf = pygame.transform.smoothscale(surf, new_size)
    return surf


# --------------------------------------------------------------------------- #
# Main loop                                                                    #
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Artillery Duel")
    parser.add_argument(
        "--res",
        type=_parse_resolution,
        default="600p",
        metavar="RES",
        help="Resolution: 600p, 720p, 1080p, 1440p, or WxH (default: 600p)",
    )
    parser.add_argument(
        "--style",
        choices=["modern", "original"],
        default="modern",
        help="Visual style: modern (default) or original (C64-inspired)",
    )
    args = parser.parse_args()

    res_w, res_h = args.res if isinstance(args.res, tuple) else _parse_resolution(args.res)
    scaling.init(res_w, res_h)

    pygame.init()
    screen = pygame.display.set_mode((scaling.width, scaling.height))
    pygame.display.set_caption("Artillery Duel")
    clock = pygame.time.Clock()

    sounds.init()

    global _background
    if _BG_PATH.exists():
        _background = _load_background(scaling.width, scaling.height)

    body_surf   = _load_and_scale_sprite(_IMAGES / "tank_scaled.png",       _BASE_BODY_SIZE)
    barrel_surf = _load_and_scale_sprite(_IMAGES / "barrel_scaled.png",    _BASE_BARREL_SIZE)
    damage_surfs = [
        _load_and_scale_sprite(_IMAGES / "tank_dam_st1_scaled.png", _BASE_BODY_SIZE),
        _load_and_scale_sprite(_IMAGES / "tank_dam_st2_scaled.png", _BASE_BODY_SIZE),
        _load_and_scale_sprite(_IMAGES / "tank_dam_st3_scaled.png", _BASE_BODY_SIZE),
        _load_and_scale_sprite(_IMAGES / "tank_dest_scaled.png",    _BASE_BODY_SIZE),
    ]

    state   = GameState(body_surf, barrel_surf, damage_surfs, style=args.style)
    console = DebugConsole(scaling.width, scaling.height)
    register_commands(console, state)
    console.print("Artillery Duel — debug console")
    console.print("Press F12 to toggle  |  type 'help' for commands")
    console.print("SPACE=fire  Left/Right=aim  Up/Down=power  Tab=switch tank")

    running = True
    while running:
        dt = clock.tick(60)
        dt_s = dt / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            if event.type == pygame.KEYDOWN and event.key == TOGGLE_KEY:
                console.toggle()
                continue

            if console.handle_event(event):
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_TAB:
                    state.active_tank = 1 - state.active_tank
                elif event.key == pygame.K_SPACE and state.shell is None:
                    tank = state.tanks[state.active_tank]
                    state.shell = Shell.fire(tank)
                    state.firing_tank_idx = state.active_tank
                    sounds.play_fire()
                    sounds.play_flight()

        # Continuous input — aim + power, skip when console is open or shell in flight
        if not console.visible and state.tanks and state.shell is None:
            keys = pygame.key.get_pressed()
            delta = ROTATION_SPEED * dt_s
            power_delta = POWER_SPEED * dt_s
            tank  = state.tanks[state.active_tank]
            if keys[pygame.K_LEFT]:
                tank.aim_angle = max(AIM_MIN, tank.aim_angle - delta)
            if keys[pygame.K_RIGHT]:
                tank.aim_angle = min(AIM_MAX, tank.aim_angle + delta)
            if keys[pygame.K_UP]:
                tank.power = min(1.0, tank.power + power_delta)
            if keys[pygame.K_DOWN]:
                tank.power = max(0.0, tank.power - power_delta)

        # Shell physics
        if state.shell is not None and state.shell.alive:
            state.shell.update(dt_s)
            hit = state.shell.check_collision(
                state.terrain, state.tanks, state.firing_tank_idx,
            )
            if hit in ("terrain", "tank"):
                sounds.stop_flight()
                sounds.play_explosion()
                ix, iy = round(state.shell.x), round(state.shell.y)
                state.explosions.append((ix, iy, state.explosion_radius, _EXPLOSION_DURATION))
                if hit == "tank" and state.shell.hit_tank_idx is not None:
                    state.tanks[state.shell.hit_tank_idx].register_hit()
                state.terrain.carve_crater(ix, iy, round(state.explosion_radius))
                state.surface = state._make_surface()
                state.shell = None
            elif hit == "offscreen":
                sounds.stop_flight()
                state.shell = None

        # Fade explosions
        state.explosions = [
            (x, y, r, t - dt_s)
            for x, y, r, t in state.explosions
            if t - dt_s > 0
        ]

        console.update(dt)

        # ---- Draw ----
        screen.blit(state.surface, (0, 0))
        for i, tank in enumerate(state.tanks):
            tank.draw(
                screen,
                show_turret_dot=state.debug_pivot,
                show_barrel_debug=state.debug_pivot and (i == state.active_tank),
            )
        _draw_active_marker(screen, state.tanks[state.active_tank])
        _draw_power_indicator(screen, state.tanks[state.active_tank])
        if state.shell is not None:
            state.shell.draw(screen)
        _draw_explosions(screen, state.explosions)
        console.draw(screen)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
