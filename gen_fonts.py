#!/usr/bin/env python3
"""Build-time font rasteriser (Pillow allowed here, and ONLY here).

Reads the Liberation Sans TTFs in fonts/ and packs every glyph we need
into fonts.bin: per glyph an advance, a bounding box and 4-bit coverage,
zlib-compressed behind a tiny magic header.  main.py re-implements the
reader with the standard library alone, so the submitted program itself
never touches a third-party library.
"""
import os
import struct
import zlib

from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Printable ASCII plus the handful of extra characters the page uses
# (the euro sign joined the set this year: the EU's Ukraine loan lead).
EXTRA = "£€·á–—‘’“”…×"
CHARSET = "".join(chr(c) for c in range(32, 127)) + EXTRA

# (name, ttf file, pixel size) -- main.py hard-codes the same order.
FONTS = [
    ("bold60", "LiberationSans-Bold.ttf", 60),
    ("bold24", "LiberationSans-Bold.ttf", 24),
    ("bold20", "LiberationSans-Bold.ttf", 20),
    ("bold17", "LiberationSans-Bold.ttf", 17),
    ("bold14", "LiberationSans-Bold.ttf", 14),
    ("bold12", "LiberationSans-Bold.ttf", 12),
    ("bold11", "LiberationSans-Bold.ttf", 11),
    ("bold10", "LiberationSans-Bold.ttf", 10),
    ("reg14", "LiberationSans-Regular.ttf", 14),
    ("reg11", "LiberationSans-Regular.ttf", 11),
    ("reg10", "LiberationSans-Regular.ttf", 10),
]

MAGIC = b"FNT1"


def pack_font(ttf_path, size):
    font = ImageFont.truetype(ttf_path, size)
    out = bytearray()
    out += struct.pack("<H", len(CHARSET))
    for ch in CHARSET:
        bbox = font.getbbox(ch)  # (x0, y0, x1, y1) vs. ascender-top anchor
        advance = int(round(font.getlength(ch)))
        if bbox is None:
            out += struct.pack("<BhhBB", advance, 0, 0, 0, 0)
            continue
        x0, y0, x1, y1 = bbox
        w = max(0, x1 - x0)
        h = max(0, y1 - y0)
        out += struct.pack("<BhhBB", advance, x0, y0, w, h)
        if w and h:
            mask = font.getmask(ch)
            px = list(mask)
            mw, mh = mask.size
            vals = []
            for yy in range(h):
                for xx in range(w):
                    if xx < mw and yy < mh:
                        vals.append(px[yy * mw + xx] >> 4)
                    else:
                        vals.append(0)
            for i in range(0, len(vals), 2):
                hi = vals[i]
                lo = vals[i + 1] if i + 1 < len(vals) else 0
                out.append((hi << 4) | lo)
    return bytes(out)


def main():
    blob = bytearray()
    blob += struct.pack("<B", len(FONTS))
    for _name, ttf, size in FONTS:
        blob += pack_font(os.path.join(HERE, "fonts", ttf), size)
    payload = MAGIC + zlib.compress(bytes(blob), 9)
    with open(os.path.join(HERE, "fonts.bin"), "wb") as fh:
        fh.write(payload)
    print("fonts.bin:", len(payload), "bytes")


if __name__ == "__main__":
    main()
