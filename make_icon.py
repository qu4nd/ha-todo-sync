"""Render brand/icon.png (256x256) and icon@2x.png (512x512) without third-party libraries."""
import struct
import zlib
from pathlib import Path

BLUE, WHITE = (3, 169, 244), (255, 255, 255)


def rrect(x, y, x0, y0, w, h, r):
    if not (x0 <= x < x0 + w and y0 <= y < y0 + h):
        return False
    cx = min(max(x, x0 + r), x0 + w - r)
    cy = min(max(y, y0 + r), y0 + h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def seg(x, y, ax, ay, bx, by, t):
    dx, dy = bx - ax, by - ay
    k = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return (x - ax - k * dx) ** 2 + (y - ay - k * dy) ** 2 <= (t / 2) ** 2


LINES = [(148, 108, 220, 108), (202, 90, 220, 108), (202, 126, 220, 108),
         (220, 148, 148, 148), (166, 130, 148, 148), (166, 166, 148, 148)]


def sample(x, y):
    """Colour at design coordinates (256 grid), or None if transparent."""
    if not rrect(x, y, 0, 0, 256, 256, 48):
        return None
    for i in range(3):
        oy = 60 + 54 * i
        if rrect(x, y, 36, oy, 28, 28, 6) or rrect(x, y, 76, oy + 6, 60, 16, 8):
            return WHITE
    if any(seg(x, y, *l, 10) for l in LINES):
        return WHITE
    if rrect(x, y, 156, 60, 64, 136, 10):
        return tuple(int(b * 0.65 + w * 0.35) for b, w in zip(BLUE, WHITE))
    return BLUE


def render(size, ss=3):
    rows = []
    scale = 256 / size
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc, n = [0, 0, 0], 0
            for sy in range(ss):
                for sx in range(ss):
                    c = sample((px + (sx + .5) / ss) * scale, (py + (sy + .5) / ss) * scale)
                    if c:
                        n += 1
                        for i in range(3):
                            acc[i] += c[i]
            a = round(255 * n / (ss * ss))
            row += bytes([acc[i] // n if n else 0 for i in range(3)] + [a])
        rows.append(bytes(row))
    return rows


def png(path, size):
    raw = b"".join(render(size))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))

    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    Path(path).write_bytes(data)


if __name__ == "__main__":
    out = Path("custom_components/todo_sync/brand")
    png(out / "icon.png", 256)
    png(out / "icon@2x.png", 512)
