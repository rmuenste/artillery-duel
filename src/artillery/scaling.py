"""Resolution-independence via height-based scaling.

Call :func:`init` once at startup with the target resolution.
All other modules read :data:`scale`, :data:`width`, and :data:`height`.
"""

BASE_HEIGHT: int = 600

# Set once at startup by init()
scale: float = 1.0
width: int = 800
height: int = 600


def init(w: int, h: int) -> None:
    global scale, width, height
    width, height = w, h
    scale = h / BASE_HEIGHT
