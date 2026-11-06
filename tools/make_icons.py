"""Draw the extension's icons with the standard library. Run: python tools/make_icons.py"""
import math
import pathlib
import struct
import zlib

SHIELD = (30, 58, 95)
CHECK = (74, 222, 128)
SAMPLES = 4


def in_shield(x, y):
    """Coordinates run from -1 to 1. Straight sides that curve to a point at the bottom."""
    if y < -0.92 or y > 0.98:
        return False
    if y < 0.05:
        half_width = 0.82 - max(0.0, (-0.6 - y)) * 0.25
    else:
        half_width = 0.82 * math.sqrt(max(0.0, 1 - ((y - 0.05) / 0.93) ** 2))
    return abs(x) <= half_width


def distance_to_segment(x, y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def in_check(x, y):
    return (distance_to_segment(x, y, -0.38, 0.0, -0.1, 0.3) < 0.13
            or distance_to_segment(x, y, -0.1, 0.3, 0.42, -0.3) < 0.13)


def draw(size):
    rows = []
    for row in range(size):
        pixels = bytearray([0])
        for column in range(size):
            shield = check = 0
            for sx in range(SAMPLES):
                for sy in range(SAMPLES):
                    x = (column + (sx + 0.5) / SAMPLES) / size * 2 - 1
                    y = (row + (sy + 0.5) / SAMPLES) / size * 2 - 1
                    if in_shield(x, y):
                        if in_check(x, y):
                            check += 1
                        else:
                            shield += 1
            total = shield + check
            if total == 0:
                pixels += bytes((0, 0, 0, 0))
                continue
            color = [round((SHIELD[i] * shield + CHECK[i] * check) / total) for i in range(3)]
            pixels += bytes((*color, round(255 * total / SAMPLES ** 2)))
        rows.append(bytes(pixels))
    return b"".join(rows)


def png(size):
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data))

    header = struct.pack("!IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(draw(size), 9)) + chunk(b"IEND", b""))


def main():
    target = pathlib.Path(__file__).resolve().parent.parent / "extension" / "icons"
    target.mkdir(exist_ok=True)
    for size in (16, 32, 48, 128):
        (target / f"icon{size}.png").write_bytes(png(size))
    print(f"Wrote icons to {target}")


if __name__ == "__main__":
    main()
