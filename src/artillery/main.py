import argparse
import enum
import math
import random
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
# Game phases                                                                  #
# --------------------------------------------------------------------------- #

class Phase(enum.Enum):
    NAME_ENTRY = "name_entry"
    DICE_ROLL = "dice_roll"
    TURN_ANNOUNCE = "turn_announce"
    AIMING = "aiming"
    SHELL_FLIGHT = "shell_flight"
    WIN_SCREEN = "win_screen"
    PLAY_AGAIN = "play_again"


# --------------------------------------------------------------------------- #
# Mutable game state                                                           #
# --------------------------------------------------------------------------- #

_BASE_EXPLOSION_RADIUS: float = 20.0
_BASE_WIND_MAX: float = 150.0  # max wind acceleration in px/s² at 600p


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

        # Wind — horizontal acceleration applied to shells (px/s², scaled)
        self.wind: float = 0.0
        self.randomize_wind()

        # Phase state
        self.phase: Phase = Phase.NAME_ENTRY
        self.player_names: list[str] = ["Player 1", "Player 2"]
        self.name_buffers: list[str] = ["", ""]
        self.name_entry_active: int = 0

        # Dice roll state
        self.dice_value: int = 1
        self.dice_timer: float = 0.0
        self.dice_interval: float = 0.05
        self.dice_next_tick: float = 0.0
        self.dice_settled: bool = False

        # Turn announce
        self.turn_announce_timer: float = 0.0

        # Win screen
        self.win_player: int = 0
        self.win_timer: float = 0.0

    def randomize_wind(self) -> None:
        """Pick a new random wind value in [-max, +max], scaled to resolution."""
        self.wind = random.uniform(-_BASE_WIND_MAX, _BASE_WIND_MAX) * scaling.scale

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

    def reset_for_new_game(self) -> None:
        """Reset for a new game, keeping player names."""
        self.terrain = Terrain(roughness=self.roughness)
        if self.style == 'original':
            self._mountain_surf = original_style.make_mountain_surface(self.terrain)
        self.surface = self._make_surface()
        self.tanks = self._make_tanks()
        self.shell = None
        self.explosions.clear()
        self.randomize_wind()
        self.phase = Phase.DICE_ROLL
        self.dice_value = 1
        self.dice_timer = 0.0
        self.dice_interval = 0.05
        self.dice_next_tick = 0.0
        self.dice_settled = False

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
            return f"  aim = {tank.aim_angle:.2f}"
        tank.aim_angle = max(AIM_MIN, min(AIM_MAX, float(args[0])))
        return f"  aim = {tank.aim_angle:.2f}"

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

    def cmd_wind(args: list[str]) -> str:
        s = scaling.scale
        if not args:
            base = state.wind / s if s != 0 else state.wind
            return f"  wind = {base:+.1f} (scaled: {state.wind:+.1f})"
        state.wind = float(args[0]) * s
        base = state.wind / s if s != 0 else state.wind
        return f"  wind = {base:+.1f} (scaled: {state.wind:+.1f})"

    console.register("gravity",          cmd_gravity)
    console.register("volume",           cmd_volume)
    console.register("style",            cmd_style)
    console.register("wind",             cmd_wind)


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
    """Bipolar colormap: dark blue (0) -> white (0.5) -> dark red (1)."""
    if t < 0.5:
        f = t / 0.5  # 0..1 over the blue->white half
        r = round(20 + f * 235)
        g = round(20 + f * 235)
        b = round(140 + f * 115)
    else:
        f = (t - 0.5) / 0.5  # 0..1 over the white->red half
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


def _draw_wind_indicator(screen: pygame.Surface, wind: float) -> None:
    """Draw a wind arrow and value at top-center of the screen."""
    s = scaling.scale
    font = pygame.font.SysFont("monospace", round(14 * s))
    cx = scaling.width // 2
    cy = round(20 * s)

    # Normalise wind for arrow length (relative to base max, scaled)
    max_wind = _BASE_WIND_MAX * s
    norm = wind / max_wind if max_wind != 0 else 0.0  # -1..+1
    arrow_max_len = round(60 * s)
    arrow_len = round(abs(norm) * arrow_max_len)

    # Draw arrow shaft
    if arrow_len > 2:
        arrow_y = cy
        if norm > 0:
            start_x = cx
            end_x = cx + arrow_len
        else:
            start_x = cx
            end_x = cx - arrow_len
        pygame.draw.line(screen, (255, 255, 255), (start_x, arrow_y), (end_x, arrow_y), max(1, round(2 * s)))
        # Arrowhead
        head_size = round(5 * s)
        direction = 1 if norm > 0 else -1
        pygame.draw.polygon(screen, (255, 255, 255), [
            (end_x, arrow_y),
            (end_x - direction * head_size, arrow_y - head_size),
            (end_x - direction * head_size, arrow_y + head_size),
        ])

    # Text label
    base_wind = wind / s if s != 0 else wind
    label = font.render(f"Wind: {base_wind:+.0f}", True, (255, 255, 255))
    label_rect = label.get_rect(centerx=cx, top=cy + round(8 * s))
    screen.blit(label, label_rect)


_EXPLOSION_DURATION: float = 1.0  # seconds


def _draw_explosions(screen: pygame.Surface, explosions: list[tuple[int, int, float, float]]) -> None:
    for x, y, radius, timer in explosions:
        alpha = max(0, timer / _EXPLOSION_DURATION)
        color = (255, round(160 * alpha), 0)
        pygame.draw.circle(screen, color, (x, y), round(radius), 2)


# --------------------------------------------------------------------------- #
# Overlay helpers                                                              #
# --------------------------------------------------------------------------- #

def _draw_overlay_panel(screen: pygame.Surface, width_frac: float, height_frac: float, alpha: int = 180) -> pygame.Rect:
    """Draw a centered semi-transparent dark panel and return its rect."""
    sw, sh = screen.get_size()
    pw = round(sw * width_frac)
    ph = round(sh * height_frac)
    px = (sw - pw) // 2
    py = (sh - ph) // 2
    overlay = pygame.Surface((pw, ph), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, alpha))
    screen.blit(overlay, (px, py))
    return pygame.Rect(px, py, pw, ph)


def _draw_name_entry(screen: pygame.Surface, state: GameState, font_sm: pygame.font.Font, font_lg: pygame.font.Font, font_xl: pygame.font.Font, time: float) -> None:
    panel = _draw_overlay_panel(screen, 0.5, 0.55)

    # Title
    title = font_lg.render("ARTILLERY DUEL", True, (255, 220, 50))
    screen.blit(title, title.get_rect(centerx=panel.centerx, top=panel.top + round(20 * scaling.scale)))

    s = scaling.scale
    field_w = round(200 * s)
    field_h = round(28 * s)
    cursor_visible = int(time * 2) % 2 == 0

    for i in range(2):
        label = font_sm.render(f"Player {i + 1}:", True, (200, 200, 200))
        label_y = panel.top + round((100 + i * 80) * s)
        screen.blit(label, label.get_rect(centerx=panel.centerx, top=label_y))

        # Input field
        field_x = panel.centerx - field_w // 2
        field_y = label_y + round(24 * s)
        border_color = (255, 220, 50) if i == state.name_entry_active else (120, 120, 120)
        pygame.draw.rect(screen, (30, 30, 30), (field_x, field_y, field_w, field_h))
        pygame.draw.rect(screen, border_color, (field_x, field_y, field_w, field_h), 2)

        buf = state.name_buffers[i]
        if buf:
            text_surf = font_sm.render(buf, True, (255, 255, 255))
        else:
            text_surf = font_sm.render(f"Player {i + 1}", True, (100, 100, 100))
        screen.blit(text_surf, text_surf.get_rect(midleft=(field_x + round(6 * s), field_y + field_h // 2)))

        # Blinking cursor
        if i == state.name_entry_active and cursor_visible:
            if buf:
                cursor_x = field_x + round(6 * s) + font_sm.size(buf)[0]
            else:
                cursor_x = field_x + round(6 * s)
            pygame.draw.line(screen, (255, 255, 255),
                             (cursor_x, field_y + round(4 * s)),
                             (cursor_x, field_y + field_h - round(4 * s)), max(1, round(s)))

    # Instructions
    hint = font_sm.render("Enter/Tab: next   Confirm both to start", True, (150, 150, 150))
    screen.blit(hint, hint.get_rect(centerx=panel.centerx, bottom=panel.bottom - round(15 * s)))


def _draw_dice_roll(screen: pygame.Surface, state: GameState, font_sm: pygame.font.Font, font_lg: pygame.font.Font, font_xl: pygame.font.Font) -> None:
    panel = _draw_overlay_panel(screen, 0.4, 0.45)
    s = scaling.scale

    title = font_lg.render("FIRST TURN", True, (255, 220, 50))
    screen.blit(title, title.get_rect(centerx=panel.centerx, top=panel.top + round(20 * s)))

    # Player names
    for i in range(2):
        color = (255, 255, 255)
        name_surf = font_sm.render(state.player_names[i], True, color)
        y = panel.top + round((70 + i * 30) * s)
        screen.blit(name_surf, name_surf.get_rect(centerx=panel.centerx, top=y))

    # Big dice number
    dice_color = (100, 255, 100) if state.dice_settled else (255, 255, 255)
    dice_surf = font_xl.render(str(state.dice_value), True, dice_color)
    screen.blit(dice_surf, dice_surf.get_rect(centerx=panel.centerx, centery=panel.centery + round(30 * s)))

    # Result text when settled
    if state.dice_settled:
        first = 0 if state.dice_value % 2 == 1 else 1
        result = font_sm.render(f"{state.player_names[first]} goes first!", True, (100, 255, 100))
        screen.blit(result, result.get_rect(centerx=panel.centerx, bottom=panel.bottom - round(15 * s)))


def _draw_turn_announce(screen: pygame.Surface, state: GameState, font_lg: pygame.font.Font) -> None:
    panel = _draw_overlay_panel(screen, 0.4, 0.2)
    name = state.player_names[state.active_tank]
    text = font_lg.render(f"{name}'s Turn", True, (255, 220, 50))
    screen.blit(text, text.get_rect(center=panel.center))


def _draw_win_screen(screen: pygame.Surface, state: GameState, font_xl: pygame.font.Font, font_sm: pygame.font.Font) -> None:
    panel = _draw_overlay_panel(screen, 0.5, 0.3)
    s = scaling.scale

    # Pulsing alpha via sin
    pulse = (math.sin(state.win_timer * 3.0) + 1.0) / 2.0
    alpha = round(150 + 105 * pulse)

    name = state.player_names[state.win_player]
    text_surf = font_xl.render(f"{name} WINS!", True, (255, 220, 50))
    text_surf.set_alpha(alpha)
    screen.blit(text_surf, text_surf.get_rect(centerx=panel.centerx, centery=panel.centery - round(10 * s)))

    if state.win_timer > 3.0:
        hint = font_sm.render("Press any key to continue", True, (180, 180, 180))
        screen.blit(hint, hint.get_rect(centerx=panel.centerx, bottom=panel.bottom - round(10 * s)))


def _draw_play_again(screen: pygame.Surface, font_lg: pygame.font.Font, font_sm: pygame.font.Font) -> None:
    panel = _draw_overlay_panel(screen, 0.4, 0.2)
    s = scaling.scale
    text = font_lg.render("Play Again?", True, (255, 220, 50))
    screen.blit(text, text.get_rect(centerx=panel.centerx, centery=panel.centery - round(10 * s)))
    hint = font_sm.render("Y = Yes    N/ESC = Quit", True, (180, 180, 180))
    screen.blit(hint, hint.get_rect(centerx=panel.centerx, bottom=panel.bottom - round(10 * s)))


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
    pygame.mixer.init()
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

    s = scaling.scale
    font_sm = pygame.font.SysFont("monospace", round(14 * s))
    font_lg = pygame.font.SysFont("monospace", round(28 * s))
    font_xl = pygame.font.SysFont("monospace", round(48 * s))

    state   = GameState(body_surf, barrel_surf, damage_surfs, style=args.style)
    console = DebugConsole(scaling.width, scaling.height)
    register_commands(console, state)
    console.print("Artillery Duel — debug console")
    console.print("Press F12 to toggle  |  type 'help' for commands")

    elapsed = 0.0  # total elapsed time for animations

    running = True
    while running:
        dt = clock.tick(60)
        dt_s = dt / 1000.0
        elapsed += dt_s

        # ---- Events ----
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            if event.type == pygame.KEYDOWN and event.key == TOGGLE_KEY:
                console.toggle()
                continue

            if console.handle_event(event):
                continue

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
                continue

            # Phase-specific event handling
            if event.type == pygame.KEYDOWN and state.phase == Phase.NAME_ENTRY:
                if event.key in (pygame.K_RETURN, pygame.K_TAB):
                    if state.name_entry_active == 0:
                        state.name_entry_active = 1
                    else:
                        # Confirm names
                        for i in range(2):
                            if state.name_buffers[i].strip():
                                state.player_names[i] = state.name_buffers[i].strip()
                        state.phase = Phase.DICE_ROLL
                elif event.key == pygame.K_BACKSPACE:
                    idx = state.name_entry_active
                    state.name_buffers[idx] = state.name_buffers[idx][:-1]
                elif event.unicode and event.unicode.isprintable() and len(event.unicode) == 1:
                    idx = state.name_entry_active
                    if len(state.name_buffers[idx]) < 12:
                        state.name_buffers[idx] += event.unicode

            elif event.type == pygame.KEYDOWN and state.phase == Phase.AIMING:
                if event.key == pygame.K_SPACE and state.shell is None:
                    tank = state.tanks[state.active_tank]
                    state.shell = Shell.fire(tank)
                    state.firing_tank_idx = state.active_tank
                    state.phase = Phase.SHELL_FLIGHT
                    sounds.play_fire()
                    sounds.play_flight()

            elif event.type == pygame.KEYDOWN and state.phase == Phase.WIN_SCREEN:
                if state.win_timer > 3.0:
                    state.phase = Phase.PLAY_AGAIN

            elif event.type == pygame.KEYDOWN and state.phase == Phase.PLAY_AGAIN:
                if event.key == pygame.K_y:
                    state.reset_for_new_game()
                elif event.key == pygame.K_n:
                    running = False

        # ---- Continuous input (aiming) ----
        if not console.visible and state.phase == Phase.AIMING and state.shell is None:
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

        # ---- Phase updates ----

        # Dice roll animation
        if state.phase == Phase.DICE_ROLL:
            state.dice_timer += dt_s
            if not state.dice_settled:
                if state.dice_timer >= state.dice_next_tick:
                    state.dice_value = random.randint(1, 6)
                    state.dice_interval *= 1.15
                    state.dice_next_tick = state.dice_timer + state.dice_interval
                    if state.dice_interval > 0.5:
                        state.dice_settled = True
                        state.dice_timer = 0.0  # reset for settled delay
            else:
                if state.dice_timer > 1.5:
                    state.active_tank = 0 if state.dice_value % 2 == 1 else 1
                    state.phase = Phase.TURN_ANNOUNCE
                    state.turn_announce_timer = 0.0

        # Turn announce timer
        if state.phase == Phase.TURN_ANNOUNCE:
            state.turn_announce_timer += dt_s
            if state.turn_announce_timer >= 1.5:
                state.phase = Phase.AIMING

        # Shell physics
        if state.phase == Phase.SHELL_FLIGHT and state.shell is not None and state.shell.alive:
            state.shell.update(dt_s, wind=state.wind)
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
                    if state.tanks[state.shell.hit_tank_idx].destroyed:
                        state.shell = None
                        state.win_player = state.firing_tank_idx
                        state.phase = Phase.WIN_SCREEN
                        state.win_timer = 0.0
                        state.terrain.carve_crater(ix, iy, round(state.explosion_radius))
                        state.surface = state._make_surface()
                        state.randomize_wind()
                    else:
                        state.terrain.carve_crater(ix, iy, round(state.explosion_radius))
                        state.surface = state._make_surface()
                        state.shell = None
                        state.randomize_wind()
                        state.active_tank = 1 - state.active_tank
                        state.phase = Phase.TURN_ANNOUNCE
                        state.turn_announce_timer = 0.0
                else:
                    state.terrain.carve_crater(ix, iy, round(state.explosion_radius))
                    state.surface = state._make_surface()
                    state.shell = None
                    state.randomize_wind()
                    state.active_tank = 1 - state.active_tank
                    state.phase = Phase.TURN_ANNOUNCE
                    state.turn_announce_timer = 0.0
            elif hit == "offscreen":
                sounds.stop_flight()
                state.shell = None
                state.randomize_wind()
                state.active_tank = 1 - state.active_tank
                state.phase = Phase.TURN_ANNOUNCE
                state.turn_announce_timer = 0.0

        # Win screen timer
        if state.phase == Phase.WIN_SCREEN:
            state.win_timer += dt_s

        # Fade explosions (always, so they finish during overlays)
        state.explosions = [
            (x, y, r, t - dt_s)
            for x, y, r, t in state.explosions
            if t - dt_s > 0
        ]

        console.update(dt)

        # ---- Draw ----
        # Background: terrain + tanks always drawn
        screen.blit(state.surface, (0, 0))
        for i, tank in enumerate(state.tanks):
            tank.draw(
                screen,
                show_turret_dot=state.debug_pivot,
                show_barrel_debug=state.debug_pivot and (i == state.active_tank),
            )

        # HUD elements (only during gameplay phases)
        if state.phase in (Phase.AIMING, Phase.SHELL_FLIGHT, Phase.TURN_ANNOUNCE):
            _draw_active_marker(screen, state.tanks[state.active_tank])
            _draw_power_indicator(screen, state.tanks[state.active_tank])
            _draw_wind_indicator(screen, state.wind)

        if state.shell is not None:
            state.shell.draw(screen)
        _draw_explosions(screen, state.explosions)

        # Phase overlays
        if state.phase == Phase.NAME_ENTRY:
            _draw_name_entry(screen, state, font_sm, font_lg, font_xl, elapsed)
        elif state.phase == Phase.DICE_ROLL:
            _draw_dice_roll(screen, state, font_sm, font_lg, font_xl)
        elif state.phase == Phase.TURN_ANNOUNCE:
            _draw_turn_announce(screen, state, font_lg)
        elif state.phase == Phase.WIN_SCREEN:
            _draw_win_screen(screen, state, font_xl, font_sm)
        elif state.phase == Phase.PLAY_AGAIN:
            _draw_play_again(screen, font_lg, font_sm)

        console.draw(screen)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
