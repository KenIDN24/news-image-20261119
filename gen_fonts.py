#!/usr/bin/env python3
"""Bake fonts.bin from the Liberation Sans TTFs in fonts/.

Build-time tool only: Pillow is welcome here and nowhere else.  The
submitted program (main.py) reads fonts.bin back with the standard
library alone, so the packing format is a contract between this file
and main.py's read_fonts():

    "FNT1" + zlib( u8 n_fonts,
                   per font: u16 n_glyphs,
                   per glyph: u8 advance, i16 x0, i16 y0, u8 w, u8 h,
                              ceil(w*h/2) bytes of 4-bit coverage )

Glyph coverage comes from the font's own rasteriser at each size, so
the page's letterforms are real Liberation Sans, just pre-rendered.
"""
import os
import struct
import zlib

from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Printable ASCII plus the extras the page prints (the euro sign is new
# this year, for the EU's Ukraine loan).  main.py lists the same set.
EXTRA_CHARS = "£€·á–—‘’“”…×"
CHARSET = [chr(c) for c in range(32, 127)] + list(EXTRA_CHARS)

# (ttf file, pixel size); main.py's FONT_ORDER names them in this order.
SIZES = [("LiberationSans-Bold.ttf", s) for s in (60, 24, 20, 17, 14, 12, 11, 10)]
SIZES += [("LiberationSans-Regular.ttf", s) for s in (14, 11, 10)]


def glyph_record(font, ch):
    """One glyph's header + packed 4-bit coverage, or a blank record."""
    advance = int(round(font.getlength(ch)))
    bbox = font.getbbox(ch)
    if bbox is None:
        return struct.pack("<BhhBB", advance, 0, 0, 0, 0)
    x0, y0, x1, y1 = bbox
    w, h = max(0, x1 - x0), max(0, y1 - y0)
    record = bytearray(struct.pack("<BhhBB", advance, x0, y0, w, h))
    if w and h:
        mask = font.getmask(ch)
        mw, _mh = mask.size
        cells = [((mask[y * mw + x] >> 4) if x < mw else 0)
                 for y in range(h) for x in range(w)]
        for i in range(0, len(cells), 2):
            hi = cells[i]
            lo = cells[i + 1] if i + 1 < len(cells) else 0
            record.append((hi << 4) | lo)
    return bytes(record)


def bake():
    payload = bytearray(struct.pack("<B", len(SIZES)))
    for ttf, size in SIZES:
        font = ImageFont.truetype(os.path.join(HERE, "fonts", ttf), size)
        payload += struct.pack("<H", len(CHARSET))
        for ch in CHARSET:
            payload += glyph_record(font, ch)
    blob = b"FNT1" + zlib.compress(bytes(payload), 9)
    out = os.path.join(HERE, "fonts.bin")
    with open(out, "wb") as fh:
        fh.write(blob)
    print("fonts.bin:", len(blob), "bytes")


if __name__ == "__main__":
    bake()
