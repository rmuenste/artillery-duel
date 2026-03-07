import sys
from pathlib import Path

import pygame

from .console import DebugConsole
from .tank import Tank
from .terrain import Terrain

_IMAGES = Path(__file__).parent / "assets" / "images"

TOGGLE_KEY    = pygame.K_F12
ROTATION_SPEED = 60.0   # degrees per second
AIM_MIN, AIM_MAX = 0.0, 90.0


# --------------------------------------------------------------------------- #
# Mutable game state                                                           #
# --------------------------------------------------------------------------- #

class GameState:
    def __init__(self, body_surf: pygame.Surface, barrel_surf: pygame.Surface) -> None:
        self.roughness: float = 0.6
        self._body   = body_surf
        self._barrel = barrel_surf
        self.terrain = Terrain(roughness=self.roughness)
        self.surface = self._make_surface()
        self.tanks   = self._make_tanks()

    def regen(self, seed: int | None = None, roughness: float | None = None) -> None:
        if roughness is not None:
            self.roughness = roughness
        self.terrain = Terrain(seed=seed, roughness=self.roughness)
        self.surface = self._make_surface()
        self.tanks   = self._make_tanks()

    def _make_surface(self) -> pygame.Surface:
        return pygame.surfarray.make_surface(self.terrain.to_surface_array())

    def _make_tanks(self) -> list[Tank]:
        (cx0, sy0), (cx1, sy1) = self.terrain.platforms
        return [
            Tank(self._body, self._barrel, cx0, sy0, facing="right"),  # left side, fires right
            Tank(self._body, self._barrel, cx1, sy1, facing="left"),   # right side, fires left
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
        lines = []
        for i, (cx, y) in enumerate(state.terrain.platforms):
            lines.append(f"  tank {i + 1}: center_x={cx}  x={cx - 20}..{cx + 20}  surface_y={y}")
        return "\n".join(lines)

    console.register("regen",     cmd_regen)
    console.register("roughness", cmd_roughness)
    console.register("seed",      cmd_seed)
    console.register("platforms", cmd_platforms)


# --------------------------------------------------------------------------- #
# Rendering helpers                                                            #
# --------------------------------------------------------------------------- #

def _draw_active_marker(screen: pygame.Surface, tank: Tank) -> None:
    """Draw a small downward-pointing triangle above the active tank."""
    bw, bh = tank.body.get_size()
    tip_x = tank.cx
    tip_y = tank.sy - bh + 10   # just above the body top
    points = [
        (tip_x,      tip_y),
        (tip_x - 6,  tip_y - 10),
        (tip_x + 6,  tip_y - 10),
    ]
    pygame.draw.polygon(screen, (255, 255, 0), points)


# --------------------------------------------------------------------------- #
# Main loop                                                                    #
# --------------------------------------------------------------------------- #

def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((Terrain.WIDTH, Terrain.HEIGHT))
    pygame.display.set_caption("Artillery Duel")
    clock = pygame.time.Clock()

    body_surf   = pygame.image.load(_IMAGES / "tank_scaled.png").convert_alpha()
    barrel_surf = pygame.image.load(_IMAGES / "barrel_scaled.png").convert_alpha()

    state        = GameState(body_surf, barrel_surf)
    console      = DebugConsole(Terrain.WIDTH, Terrain.HEIGHT)
    active_tank  = 0
    register_commands(console, state)
    console.print("Artillery Duel — debug console")
    console.print("Press F12 to toggle  |  type 'help' for commands")

    running = True
    while running:
        dt = clock.tick(60)

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
                    active_tank = 1 - active_tank

        # Barrel rotation — continuous while key held, skip when console is open
        if not console.visible and state.tanks:
            keys = pygame.key.get_pressed()
            delta = ROTATION_SPEED * dt / 1000.0
            tank  = state.tanks[active_tank]
            if keys[pygame.K_LEFT]:
                tank.aim_angle = max(AIM_MIN, tank.aim_angle - delta)
            if keys[pygame.K_RIGHT]:
                tank.aim_angle = min(AIM_MAX, tank.aim_angle + delta)

        console.update(dt)

        screen.blit(state.surface, (0, 0))
        for tank in state.tanks:
            tank.draw(screen)
        _draw_active_marker(screen, state.tanks[active_tank])
        console.draw(screen)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
