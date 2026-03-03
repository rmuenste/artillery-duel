from __future__ import annotations

from collections import deque
from typing import Callable

import pygame

# Visual constants
CONSOLE_HEIGHT_RATIO = 0.40
BG_COLOR = (10, 10, 10, 200)
OUTPUT_COLOR = (0, 220, 80)     # terminal green
INPUT_COLOR = (255, 255, 255)
PROMPT = "> "
FONT_SIZE = 14
LINE_PAD = 2


class DebugConsole:
    """Quake-style drop-down console overlay.

    Toggle visibility with the backtick key from outside.
    Register game commands via :meth:`register`.
    """

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.width = screen_width
        self.panel_height = int(screen_height * CONSOLE_HEIGHT_RATIO)
        self.visible = False

        self._font = pygame.font.SysFont("monospace", FONT_SIZE)
        self._line_h = self._font.get_linesize() + LINE_PAD
        self._max_output_lines = (self.panel_height - self._line_h - 8) // self._line_h

        self._output: deque[str] = deque(maxlen=200)
        self._input: str = ""
        self._history: list[str] = []
        self._hist_pos: int = -1         # -1 = live input, 0 = most recent

        self._commands: dict[str, Callable[[list[str]], str | None]] = {}

        self._cursor_on = True
        self._cursor_ms = 0

        self._surface = pygame.Surface((self.width, self.panel_height), pygame.SRCALPHA)

        self._register_builtins()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def toggle(self) -> None:
        self.visible = not self.visible
        if self.visible:
            self._input = ""
            self._hist_pos = -1

    def register(self, name: str, handler: Callable[[list[str]], str | None]) -> None:
        self._commands[name] = handler

    def print(self, text: str) -> None:
        for line in str(text).split("\n"):
            self._output.append(line)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Process a pygame event.  Returns True if the console consumed it."""
        if not self.visible:
            return False
        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event)
            return True
        return False

    def update(self, dt_ms: int) -> None:
        self._cursor_ms += dt_ms
        if self._cursor_ms >= 500:
            self._cursor_ms = 0
            self._cursor_on = not self._cursor_on

    def draw(self, screen: pygame.Surface) -> None:
        if not self.visible:
            return

        self._surface.fill(BG_COLOR)

        # Output lines
        visible = list(self._output)[-self._max_output_lines:]
        y = 4
        for line in visible:
            surf = self._font.render(line, True, OUTPUT_COLOR)
            self._surface.blit(surf, (6, y))
            y += self._line_h

        # Input line
        cursor = "_" if self._cursor_on else " "
        surf = self._font.render(PROMPT + self._input + cursor, True, INPUT_COLOR)
        self._surface.blit(surf, (6, self.panel_height - self._line_h - 4))

        screen.blit(self._surface, (0, 0))

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        key = event.key

        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            cmd = self._input.strip()
            if cmd:
                self._history.append(cmd)
                self._hist_pos = -1
                self._execute(cmd)
            self._input = ""

        elif key == pygame.K_BACKSPACE:
            self._input = self._input[:-1]

        elif key == pygame.K_UP:
            if self._history:
                self._hist_pos = min(self._hist_pos + 1, len(self._history) - 1)
                self._input = self._history[-(self._hist_pos + 1)]

        elif key == pygame.K_DOWN:
            if self._hist_pos > 0:
                self._hist_pos -= 1
                self._input = self._history[-(self._hist_pos + 1)]
            else:
                self._hist_pos = -1
                self._input = ""

        elif event.unicode and event.unicode.isprintable():
            self._input += event.unicode

    def _execute(self, raw: str) -> None:
        self.print(PROMPT + raw)
        parts = raw.split()
        name, args = parts[0].lower(), parts[1:]
        if name not in self._commands:
            self.print(f"  unknown command '{name}' — try 'help'")
            return
        try:
            result = self._commands[name](args)
            if result:
                self.print(result)
        except Exception as exc:
            self.print(f"  error: {exc}")

    # ------------------------------------------------------------------ #
    # Built-in commands                                                    #
    # ------------------------------------------------------------------ #

    def _register_builtins(self) -> None:
        def cmd_help(args: list[str]) -> str:
            return "commands: " + "  ".join(sorted(self._commands))

        def cmd_clear(args: list[str]) -> None:
            self._output.clear()

        self.register("help", cmd_help)
        self.register("clear", cmd_clear)
