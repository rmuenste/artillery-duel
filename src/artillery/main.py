import sys

import pygame

from .console import DebugConsole
from .terrain import Terrain

TOGGLE_KEY = pygame.K_F12

TANK_COLOR = (30, 110, 30)   # dark green
TANK_SIZE  = 40


# --------------------------------------------------------------------------- #
# Mutable game state                                                           #
# --------------------------------------------------------------------------- #

class GameState:
    def __init__(self) -> None:
        self.roughness: float = 0.6
        self.terrain = Terrain(roughness=self.roughness)
        self.surface: pygame.Surface = self._make_surface()

    def regen(self, seed: int | None = None, roughness: float | None = None) -> None:
        if roughness is not None:
            self.roughness = roughness
        self.terrain = Terrain(seed=seed, roughness=self.roughness)
        self.surface = self._make_surface()

    def _make_surface(self) -> pygame.Surface:
        return pygame.surfarray.make_surface(self.terrain.to_surface_array())


# --------------------------------------------------------------------------- #
# Command registration                                                         #
# --------------------------------------------------------------------------- #

def _parse_seed_arg(args: list[str]) -> int | None:
    """Accept positional (42) or keyword (seed=42) seed argument."""
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

    console.register("regen", cmd_regen)
    console.register("roughness", cmd_roughness)
    console.register("seed", cmd_seed)
    console.register("platforms", cmd_platforms)


# --------------------------------------------------------------------------- #
# Rendering helpers                                                            #
# --------------------------------------------------------------------------- #

def _draw_tanks(screen: pygame.Surface, platforms: list[tuple[int, int]]) -> None:
    for cx, surface_y in platforms:
        rect = pygame.Rect(cx - TANK_SIZE // 2, surface_y - TANK_SIZE, TANK_SIZE, TANK_SIZE)
        pygame.draw.rect(screen, TANK_COLOR, rect)


# --------------------------------------------------------------------------- #
# Main loop                                                                    #
# --------------------------------------------------------------------------- #

def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((Terrain.WIDTH, Terrain.HEIGHT))
    pygame.display.set_caption("Artillery Duel")
    clock = pygame.time.Clock()

    state = GameState()
    console = DebugConsole(Terrain.WIDTH, Terrain.HEIGHT)
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

            # Toggle console (not forwarded further)
            if event.type == pygame.KEYDOWN and event.key == TOGGLE_KEY:
                console.toggle()
                continue

            # Console eats all input while open
            if console.handle_event(event):
                continue

            # Game-level keys (console closed)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        console.update(dt)

        screen.blit(state.surface, (0, 0))
        _draw_tanks(screen, state.terrain.platforms)
        console.draw(screen)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
