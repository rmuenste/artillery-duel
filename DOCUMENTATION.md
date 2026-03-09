# Artillery Duel — Documentation

A classic C64-style two-player artillery duel game built with pygame-ce. Players take turns adjusting aim and power, then fire shells across procedurally generated terrain.

---

## Running the Game

```
artillery-duel [--res RESOLUTION]
```

**Resolution presets:** `600p` (800×600, default), `720p`, `1080p`, `1440p`
**Custom resolution:** `--res 1024x768`

All dimensions, physics, and UI elements scale automatically to the target resolution.

---

## Controls

| Key | Action |
|-----|--------|
| `SPACE` | Fire |
| `LEFT` / `RIGHT` | Adjust aim angle |
| `UP` / `DOWN` | Adjust power |
| `TAB` | Switch active tank |
| `F12` | Toggle debug console |
| `ESC` | Quit |

---

## Architecture Overview

```
main.py        — game loop, input, rendering, command registration
scaling.py     — resolution-independent scale factor
terrain.py     — procedural terrain generation
tank.py        — tank model, sprite composition, barrel rotation
shell.py       — projectile physics and collision detection
console.py     — debug console UI
sounds.py      — audio loading and playback
```

---

## Module Reference

### `scaling.py`

Provides a global scale factor derived from the target screen height relative to the 600p reference resolution.

| Symbol | Description |
|--------|-------------|
| `BASE_HEIGHT` | Reference height: 600 px |
| `scale` | Multiplier: `height / BASE_HEIGHT` |
| `width`, `height` | Current screen dimensions |
| `init(w, h)` | Initialize scaling — call once at startup |

All other modules read `scaling.scale` to size sprites, physics constants, and UI elements.

---

### `terrain.py` — `Terrain`

Generates a landscape using **1D midpoint displacement** (fractal terrain).

**Constructor:** `Terrain(seed=None, roughness=0.6)`

| Attribute | Description |
|-----------|-------------|
| `seed` | RNG seed for reproducibility |
| `roughness` | Fractal dimension control (0, 2] — higher = more jagged |
| `heights` | 1D int array of surface y-positions per column |
| `platforms` | Two flat zones: `[(cx, sy), (cx, sy)]` for tank placement |
| `pixels` | 2D bool array — `True` where terrain is solid |

**Key methods:**

| Method | Description |
|--------|-------------|
| `to_surface_array()` | Returns a `(W, H, 3)` uint8 RGB array for `pygame.surfarray` |
| `carve_crater(cx, cy, radius)` | Removes terrain in a circle (used on shell impact) |

**Terrain generation details:**
- Random start/end heights at ~55% screen height
- Recursive midpoint displacement: each level's displacement scales by `2^(-roughness)`
- Heights clamped to [15%, 88%] of screen height
- Two flat platform zones at 0–15% and 85–100% of screen width
- Surface rendered with a mountain texture blended over a sky-blue background

---

### `tank.py` — `Tank`

Composed of two sprites: a static body and a rotating barrel.

**Constructor:** `Tank(body_surf, barrel_surf, cx, sy, facing)`

| Parameter | Description |
|-----------|-------------|
| `cx, sy` | Platform center x and surface y |
| `facing` | `"right"` (left tank) or `"left"` (right tank) |

| Attribute | Description |
|-----------|-------------|
| `aim_angle` | Barrel angle in degrees (0–90) |
| `power` | Normalised shot power (0.0–1.0) |

**Key methods:**

| Method | Description |
|--------|-------------|
| `muzzle_pos()` | Screen position of the barrel tip |
| `turret_screen_pos()` | Screen position of the barrel attachment point on the body |
| `body_rect()` | Axis-aligned bounding box of the tank body |
| `hit_test(sx, sy)` | Pixel-perfect hit detection using the body sprite's alpha channel |
| `draw(screen, ...)` | Render body, barrel, and optional debug overlays |

**Tunable constants (also adjustable via console):**

| Constant | Default | Description |
|----------|---------|-------------|
| `BARREL_NATURAL_ANGLE` | `1.5°` | Barrel's resting angle in the source image |
| `TURRET_ON_BODY` | `(0.50, 0.45)` | Relative attachment point of the barrel on the body |
| `BREECH_ON_BARREL` | `(0.66, 0.50)` | Relative rotation pivot on the barrel sprite |

**Barrel rotation** uses the Ruler Analogy: compute the breech-to-center vector, rotate it by the aim angle, then offset the blitted surface so the pivot stays fixed on screen.

---

### `shell.py` — `Shell`

Models a projectile under gravity.

**Factory method:** `Shell.fire(tank)` — creates a shell from the tank's muzzle position, aim angle, and power.

| Attribute | Description |
|-----------|-------------|
| `x, y` | Float position (sub-pixel precision) |
| `vx, vy` | Velocity in px/s |
| `alive` | False once the shell has hit something |

**Key methods:**

| Method | Description |
|--------|-------------|
| `update(dt_s)` | Advance physics: apply gravity, update position |
| `check_collision(terrain, tanks, firing_tank_idx)` | Returns `'terrain'`, `'tank'`, `'offscreen'`, or `None` |
| `draw(screen)` | Render shell as a white circle |

**Tunable constants:**

| Constant | Default (600p) | Description |
|----------|----------------|-------------|
| `_BASE_GRAVITY` | `500 px/s²` | Gravity (scales with resolution) |
| `_BASE_POWER_MIN` | `100 px/s` | Minimum muzzle velocity |
| `_BASE_POWER_MAX` | `800 px/s` | Maximum muzzle velocity |

---

### `console.py` — `DebugConsole`

A Quake-style drop-down console overlay.

**Constructor:** `DebugConsole(screen_width, screen_height)`

| Method | Description |
|--------|-------------|
| `toggle()` | Show/hide the console |
| `register(name, handler)` | Add a command: `handler(args: list[str]) -> str` |
| `print(text)` | Append a line to the output |
| `handle_event(event)` | Returns `True` if the console consumed the event |
| `update(dt_ms)` | Update cursor blink |
| `draw(screen)` | Render the console overlay |

The console captures all keyboard input when visible. Command history is navigable with `UP` / `DOWN`.

---

### `sounds.py`

Loads audio from `assets/sounds/artillery_shell.wav` (a 5-second combined file) and slices it into three separate sounds. Falls back to procedural numpy generation if the file is missing.

**WAV time ranges:**

| Sound | Slice |
|-------|-------|
| Fire | 0.15 – 1.0 s |
| Explosion | 1.9 – 3.0 s |
| Flight (looped) | 3.0 – 5.0 s |

**Public API:**

| Function | Description |
|----------|-------------|
| `init()` | Load/generate all sounds — call after `pygame.mixer.init()` |
| `set_volume(vol)` | Set master volume (0.0 – 1.0) |
| `play_fire()` | Play the cannon fire sound once |
| `play_flight()` | Start looping the flight whistle |
| `stop_flight()` | Stop the flight whistle |
| `play_explosion()` | Play the explosion sound once |

---

## Debug Console

Press **F12** to open the debug console. Type a command and press **Enter**.

### Available Commands

#### Terrain

| Command | Description |
|---------|-------------|
| `regen [seed]` | Regenerate terrain, optionally with a specific seed |
| `roughness [value]` | Get or set terrain roughness `(0, 2]` |
| `seed` | Print the current terrain seed |
| `platforms` | Print tank platform positions |

#### Tank & Aiming

| Command | Description |
|---------|-------------|
| `aim [angle]` | Get or set active tank aim angle (0–90°) |
| `power [0–1]` | Get or set active tank power (normalised) |
| `turret [x] [y]` | Get or set barrel attachment point on body (relative coords) |
| `breech [x] [y]` | Get or set barrel rotation pivot (relative coords) |
| `natural_angle [deg]` | Get or set barrel's natural angle in the sprite |

#### Physics

| Command | Description |
|---------|-------------|
| `gravity [px/s²]` | Get or set gravity (base value at 600p) |
| `explosion_radius [px]` | Get or set explosion blast radius |

#### Audio

| Command | Description |
|---------|-------------|
| `volume [0–1]` | Get or set master volume |

#### Debug

| Command | Description |
|---------|-------------|
| `debug_pivot` | Toggle turret pivot and barrel debug overlay |
| `help` | List all available commands |
| `clear` | Clear console output |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pygame-ce` | ≥ 2.5.0 | Rendering, input, audio |
| `numpy` | ≥ 1.26.0 | Terrain generation, sound synthesis |
