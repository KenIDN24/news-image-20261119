#!/usr/bin/env python3
"""THE DAY IN WORLD NEWS -- Thursday 19 November 2026.

A one-page newspaper front page (1024x1024 PNG) that sums up the day's
world news, drawn with nothing but the Python standard library.  The
glyphs arrive pre-rasterised in fonts.bin (baked by gen_fonts.py, a
build-time tool that never ships its library with the program).
Output is deterministic: no randomness, no clock, no network.
"""
import os
import struct
import sys
import zlib

# ------------------------------------------------------------------ fonts
#
# fonts.bin layout: magic "FNT1", then zlib of:
#   u8  number of fonts
#   per font: u16 glyph count, then per glyph
#     u8 advance, i16 x0, i16 y0, u8 w, u8 h, ceil(w*h/2) bytes of
#     4-bit coverage (high nibble first)
# The character set and the font order below are baked into the file by
# gen_fonts.py; the two must agree, so they are written side by side.

EXTRA_CHARS = "£€·á–—‘’“”…×"
CHARSET = [chr(c) for c in range(32, 127)] + list(EXTRA_CHARS)
FONT_ORDER = ("bold60", "bold24", "bold20", "bold17", "bold14",
              "bold12", "bold11", "bold10", "reg14", "reg11", "reg10")


def read_fonts(path):
    blob = open(path, "rb").read()
    if blob[:4] != b"FNT1":
        raise ValueError("fonts.bin: bad magic")
    raw = zlib.decompress(blob[4:])
    fonts = {}
    pos = 0
    n_fonts = raw[pos]
    pos += 1
    for fi in range(n_fonts):
        (n_glyphs,) = struct.unpack_from("<H", raw, pos)
        pos += 2
        table = {}
        for ci in range(n_glyphs):
            adv, x0, y0, w, h = struct.unpack_from("<BhhBB", raw, pos)
            pos += 7
            nbytes = (w * h + 1) // 2
            table[CHARSET[ci]] = (w, h, x0, y0, adv, raw[pos:pos + nbytes])
            pos += nbytes
        fonts[FONT_ORDER[fi]] = table
    return fonts


FONTS = {}


def measure(font_name, text, tracking=0):
    table = FONTS[font_name]
    width = 0
    for ch in text:
        glyph = table.get(ch) or table["?"]
        width += glyph[4] + tracking
    return width - tracking if text else 0


def wrap(font_name, text, limit):
    """Greedy wrap: split text into lines no wider than limit pixels."""
    lines, current = [], ""
    for word in text.split():
        trial = word if not current else current + " " + word
        if measure(font_name, trial) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ------------------------------------------------------------------ page

class Page:
    """A 1024x1024 RGB raster with drawing and text primitives."""

    def __init__(self, size, background):
        self.size = size
        self.px = bytearray(background) * (size * size)

    def put(self, x, y, colour):
        if 0 <= x < self.size and 0 <= y < self.size:
            i = (y * self.size + x) * 3
            self.px[i:i + 3] = bytes(colour)

    def blend(self, x, y, colour, cov):
        # cov: glyph coverage, 0..15
        if cov == 0 or not (0 <= x < self.size and 0 <= y < self.size):
            return
        i = (y * self.size + x) * 3
        if cov == 15:
            self.px[i:i + 3] = bytes(colour)
        else:
            keep = 15 - cov
            for k in range(3):
                self.px[i + k] = (self.px[i + k] * keep
                                  + colour[k] * cov) // 15

    def fill(self, x, y, w, h, colour):
        x_lo, y_lo = max(0, x), max(0, y)
        x_hi, y_hi = min(self.size, x + w), min(self.size, y + h)
        if x_hi <= x_lo or y_hi <= y_lo:
            return
        strip = bytes(colour) * (x_hi - x_lo)
        for yy in range(y_lo, y_hi):
            start = (yy * self.size + x_lo) * 3
            self.px[start:start + len(strip)] = strip

    def box(self, x, y, w, h, colour, t=1):
        self.fill(x, y, w, t, colour)
        self.fill(x, y + h - t, w, t, colour)
        self.fill(x, y, t, h, colour)
        self.fill(x + w - t, y, t, h, colour)

    def disc(self, cx, cy, r, colour):
        rr = r * r
        for yy in range(cy - r, cy + r + 1):
            span = int((rr - (yy - cy) ** 2) ** 0.5) if rr >= (yy - cy) ** 2 else -1
            if span >= 0:
                self.fill(cx - span, yy, span * 2 + 1, 1, colour)

    def ring(self, cx, cy, r, colour, t=2):
        inner = (r - t) ** 2
        outer = r * r
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if inner <= (xx - cx) ** 2 + (yy - cy) ** 2 <= outer:
                    self.put(xx, yy, colour)

    def oval(self, cx, cy, rx, ry, colour):
        if rx <= 0 or ry <= 0:
            return
        for yy in range(cy - ry, cy + ry + 1):
            frac = 1.0 - ((yy - cy) / ry) ** 2
            if frac < 0:
                continue
            span = int(rx * frac ** 0.5)
            self.fill(cx - span, yy, span * 2 + 1, 1, colour)

    def seg(self, x0, y0, x1, y1, colour, t=1):
        # Bresenham, drawn as a small square brush of thickness t
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        half = t // 2
        while True:
            self.fill(x0 - half, y0 - half, t, t, colour)
            if (x0, y0) == (x1, y1):
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def poly(self, points, colour):
        # scanline fill: collect edge crossings per row, fill pairs
        n = len(points)
        y_lo = max(0, min(p[1] for p in points))
        y_hi = min(self.size - 1, max(p[1] for p in points))
        for yy in range(y_lo, y_hi + 1):
            crossings = []
            for i in range(n):
                xa, ya = points[i]
                xb, yb = points[(i + 1) % n]
                if (ya <= yy < yb) or (yb <= yy < ya):
                    crossings.append(xa + (yy - ya) * (xb - xa) / (yb - ya))
            crossings.sort()
            for i in range(0, len(crossings) - 1, 2):
                xa, xb = int(crossings[i]), int(crossings[i + 1])
                self.fill(xa, yy, xb - xa + 1, 1, colour)

    # ------------------------------------------------------------- text
    def draw(self, font_name, x, y, text, colour, tracking=0):
        table = FONTS[font_name]
        pen = x
        for ch in text:
            glyph = table.get(ch) or table["?"]
            w, h, x0, y0, adv, packed = glyph
            idx = 0
            for row in range(h):
                for col in range(w):
                    byte = packed[idx >> 1]
                    cov = (byte >> 4) if idx % 2 == 0 else (byte & 15)
                    idx += 1
                    if cov:
                        self.blend(pen + x0 + col, y + y0 + row, colour, cov)
            pen += adv + tracking
        return pen - x - (tracking if text else 0)

    def draw_c(self, font_name, cx, y, text, colour, tracking=0):
        return self.draw(font_name, cx - measure(font_name, text, tracking) // 2,
                         y, text, colour, tracking)

    def draw_r(self, font_name, x_right, y, text, colour, tracking=0):
        return self.draw(font_name, x_right - measure(font_name, text, tracking),
                         y, text, colour, tracking)


# ------------------------------------------------------------------ png

def save_png(page, path):
    """Write the page as a PNG: one IDAT, filter 0 rows, zlib level 9."""
    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    stride = page.size * 3
    rows = bytearray()
    for yy in range(page.size):
        rows.append(0)  # filter type 0 for every scanline
        rows += page.px[yy * stride:(yy + 1) * stride]
    header = struct.pack(">IIBBBBB", page.size, page.size, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


# ------------------------------------------------------------------ content

PAPER = (247, 243, 234)
PANEL = (253, 251, 246)
INK = (22, 24, 29)
BODY = (48, 50, 56)
FAINT = (110, 105, 94)
BORDER = (203, 195, 175)
RED = (163, 38, 32)
BLUE = (30, 74, 140)
GREEN = (26, 102, 70)
TEAL = (13, 106, 122)
BROWN = (146, 96, 20)
PLUM = (138, 42, 108)
SLATE = (84, 102, 118)
SAND = (233, 226, 208)
LAND = (219, 203, 164)
SEA = (198, 213, 219)
MAPDOT = (168, 156, 128)
YELLOW = (212, 164, 32)
WHITE = (255, 255, 255)

MARGIN = 22
WIDTH = 980

# Each lead: kicker, accent colour, headline, deck, artwork key.
LEADS = [
    dict(kicker="ASIA · DIPLOMACY", colour=BROWN,
         head="Trump, Xi and Putin meet in Shenzhen",
         deck="First three-way summit of the US, Chinese and Russian "
              "leaders, at APEC: nuclear arms, Iran and trade.",
         art="summit"),
    dict(kicker="MIDDLE EAST · GAZA", colour=RED,
         head="Israeli tanks cross Gaza ceasefire line",
         deck="First ground advance beyond the Yellow Line since the "
              "2025 truce; families flee Nuseirat and Bureij.",
         art="gaza"),
    dict(kicker="AMERICAS · US POLITICS", colour=BLUE,
         head="Jeffries nominated for Speaker, 251–11",
         deck="Hakeem Jeffries is poised to be the first Black Speaker "
              "as Democrats take 259 House seats.",
         art="house"),
]

# Grid stories 4-13: kicker, accent colour, headline, one-line deck.
GRID = [
    ("BUSINESS · AI", PLUM, "Anthropic IPO is biggest ever: $81.3bn",
     "Priced at $83; Claude maker valued at $1.5tn."),
    ("EUROPE · UKRAINE", RED, "Crimea bridge hit again; Odesa toll rises",
     "Kerch traffic halted; Russian strikes kill 4."),
    ("MARKETS · US", BLUE, "Dow falls 561 as Fed hints at hike",
     "Nvidia beats yet slips 2.9% on hawkish minutes."),
    ("SCIENCE · SPACE", TEAL, "Voyager 1 passes one light-day",
     "16.1bn miles out; a signal takes 24 hours now."),
    ("CULTURE · ART", PLUM, "Van Gogh sells for record $190.4m",
     "Chestnut Trees tops $117m after Nazi-era deal."),
    ("CLIMATE · COP31", GREEN, "COP31 deadlocked with two days left",
     "21 issues open in Antalya; OPEC backs fuels."),
    ("ASIA · DEFENCE", BROWN, "India, Japan open 2+2 talks in Tokyo",
     "Defence and security ties top the agenda."),
    ("EUROPE · PROTEST", BROWN, "Prague fills streets for free media",
     "Huge rally resists a proposed media law."),
    ("WEATHER · INDIA", TEAL, "Cyclone Akvan nears India coast",
     "Landfall seen between Machilipatnam, Puri."),
    ("CULTURE · GAMING", PLUM, "GTA VI launch day stuns players",
     "Vice City queues wrap blocks on day one."),
]

# Briefs 14-38, one line each.
BRIEFS = [
    "EU proposes €45bn loan for Ukraine in 2027",
    "Coalition of the Willing meets in Berlin",
    "North Korea fires missiles after allied drill",
    "Estonia to close border crossings with Russia",
    "Spain general strike disrupts ports, factories",
    "France: fourth weekend of living-cost protests",
    "Israel taps Eisenkot to try to form government",
    "Four nations urge aid access to flooded Gaza",
    "US details $12bn in Venezuelan oil revenue",
    "Myanmar awaits ICJ ruling in Rohingya case",
    "Islam on track to be largest religion by 2035",
    "Oil falls 4.4% to $82 as US stockpiles build",
    "Gold drops 3.2% to $3,725, a 14-month low",
    "Dollar holds at a 19-month high near 103.8",
    "UnitedHealth plunges 10% on fraud proposal",
    "AMD jumps 5.3%; Palo Alto Networks up 10%",
    "Europe stocks fall 1% to a two-week low",
    "German police warn of rising hybrid threats",
    "Russian held over spying on US firm Palantir",
    "World COPD Day spotlights early diagnosis",
    "Congress targets Modi government on inflation",
    "Australia sanctions West Bank settler groups",
    "Duckett 133 puts England ahead vs Australia",
    "Veteran US actor Stacy Keach dies at 85",
    "House panel orders Trump allies to keep records",
]

# ------------------------------------------------------------------ lead art

def art_summit(pg, x, y, w, h):
    """Shenzhen skyline under a red sun, three summit flags on poles."""
    pg.fill(x, y, w, h, SAND)
    pg.disc(x + w - 52, y + 14, 9, RED)
    ground = y + h
    skyline = [(2, 22), (16, 38), (30, 18), (44, 47), (58, 30), (72, 52),
               (86, 24), (100, 41), (114, 28), (128, 55), (142, 33),
               (156, 45), (170, 21), (184, 50), (198, 36), (212, 27),
               (226, 43), (240, 31), (254, 48), (268, 25), (282, 39)]
    for off, tall in skyline:
        pg.fill(x + off, ground - tall, 12, tall, SLATE)
    pg.fill(x, ground - 2, w, 2, INK)
    # flags of the three leaders, on poles along the left
    flags = [("US", BLUE), ("CN", RED), ("RU", SLATE)]
    for i, (code, colour) in enumerate(flags):
        pole_x = x + 10 + i * 34
        pg.fill(pole_x, y + 4, 2, 26, INK)
        pg.fill(pole_x + 2, y + 4, 26, 14, colour)
        tw = measure("bold10", code)
        pg.draw("bold10", pole_x + 2 + (26 - tw) // 2, y + 6, code, WHITE)
    pg.fill(x + w - 104, y + 2, 100, 13, SAND)
    pg.draw_r("bold10", x + w - 4, y + 3, "SHENZHEN · APEC", INK)


def art_gaza(pg, x, y, w, h):
    """The Strip from above: sea, tents, a tank, the Yellow Line."""
    pg.fill(x, y, w, h, LAND)
    pg.fill(x, y, 24, h, SEA)  # the Mediterranean, along the west edge
    pg.draw("bold10", x + 4, y + 4, "GAZA", INK)
    pg.draw_r("bold10", x + w - 4, y + 4, "ISRAEL", INK)
    # refugee tents west of the line: small triangles in two rows
    for i, tx in enumerate((44, 66, 88, 110)):
        ty = y + 14 if i % 2 == 0 else y + 30
        pg.poly([(tx, ty + 10), (tx + 7, ty), (tx + 14, ty + 10)], SLATE)
    # a tank, hull and turret, barrel trained east
    tx, ty = x + 128, y + 26
    pg.fill(tx, ty + 8, 38, 11, INK)
    pg.fill(tx + 11, ty + 1, 16, 8, INK)
    pg.seg(tx + 27, ty + 4, tx + 50, ty + 4, INK, 2)
    for wx in (tx + 6, tx + 18, tx + 30):
        pg.disc(wx, ty + 21, 3, INK)
    # the Yellow Line itself: dashed, at 68% of the strip
    line_x = x + int(w * 0.68)
    dash = y + 3
    while dash < y + h - 5:
        pg.fill(line_x, dash, 3, 6, YELLOW)
        dash += 10
    pg.draw("bold10", line_x - 36, y + h - 13, "YELLOW LINE", INK)
    # a target ring on the far side of the line
    pg.ring(x + w - 40, y + 34, 7, RED, 2)
    pg.disc(x + w - 40, y + 34, 2, RED)


def art_house(pg, x, y, w, h):
    """House seats as bars, plus a dot for roughly every ten seats."""
    pg.fill(x, y, w, h, SAND)
    parties = [("DEM", BLUE, 259, y + 8), ("REP", RED, 176, y + 32)]
    for name, colour, seats, bar_y in parties:
        pg.draw("bold11", x + 8, bar_y + 2, name, colour)
        bar_len = int(seats * 0.62)
        pg.fill(x + 44, bar_y, bar_len, 13, colour)
        pg.draw("bold11", x + 44 + bar_len + 5, bar_y + 2, str(seats), INK)
    # the 218 majority mark, ticked across both bars
    tick_x = x + 44 + int(218 * 0.62)
    pg.fill(tick_x, y + 5, 2, 42, INK)
    pg.draw("bold10", tick_x - 16, y + h - 11, "218 TO WIN", BODY)
    # seat dots: one dot per ten seats, blue then red, along the bottom
    dot_x = x + 232
    for i in range(26):
        pg.disc(dot_x + (i % 13) * 5, y + 10 + (i // 13) * 9, 1, BLUE)
    for i in range(18):
        pg.disc(dot_x + (i % 13) * 5, y + 30 + (i // 13) * 9, 1, RED)


ARTWORK = {"summit": art_summit, "gaza": art_gaza, "house": art_house}

# ------------------------------------------------------------------ sections

def header_block(pg):
    pg.draw("bold20", MARGIN, 8, "THE DAY IN WORLD NEWS", INK, tracking=3)
    pg.draw_r("bold14", MARGIN + WIDTH, 13,
              "38 STORIES · 6 CONTINENTS · ONE DAY", RED)
    pg.fill(MARGIN, 38, WIDTH, 3, INK)
    pg.draw_c("bold60", MARGIN + WIDTH // 2, 48,
              "Thursday 19 November 2026", INK)
    pg.fill(MARGIN, 112, WIDTH, 3, RED)


def lead_row(pg):
    top, w, h, gap = 124, 320, 216, 10
    for i, lead in enumerate(LEADS):
        x = MARGIN + i * (w + gap)
        pg.fill(x, top, w, h, PANEL)
        pg.box(x, top, w, h, BORDER, 1)
        pg.fill(x, top, w, 4, lead["colour"])
        ARTWORK[lead["art"]](pg, x + 12, top + 12, w - 24, 62)
        pg.draw("bold12", x + 12, top + 84, lead["kicker"], lead["colour"])
        ly = top + 104
        for line in wrap("bold24", lead["head"], w - 24)[:3]:
            pg.draw("bold24", x + 12, ly, line, INK)
            ly += 27
        dy = top + 158
        for line in wrap("reg14", lead["deck"], w - 24)[:3]:
            pg.draw("reg14", x + 12, dy, line, BODY)
            dy += 17


def grid_block(pg):
    cw, ch, gap = 188, 118, 10
    for idx, (kicker, colour, head, deck) in enumerate(GRID):
        row, col = divmod(idx, 5)
        x = MARGIN + col * (cw + gap)
        y = 352 + row * (ch + gap)
        pg.fill(x, y, cw, ch, PANEL)
        pg.box(x, y, cw, ch, BORDER, 1)
        pg.fill(x, y, cw, 3, colour)
        pg.fill(x + 8, y + 9, 16, 16, RED)  # story number badge
        num = str(idx + 4)
        pg.draw("bold10", x + 8 + (16 - measure("bold10", num)) // 2,
                y + 12, num, WHITE)
        pg.draw("bold11", x + 30, y + 11, kicker, colour)
        ly = y + 32
        for line in wrap("bold17", head, cw - 16)[:3]:
            pg.draw("bold17", x + 8, ly, line, INK)
            ly += 19
        dy = y + 90
        for line in wrap("reg11", deck, cw - 16)[:2]:
            pg.draw("reg11", x + 8, dy, line, BODY)
            dy += 13

# ------------------------------------------------------------------ world map
#
# The dot-matrix map is data-driven: PLAIN_BOXES are rectangles of land
# in (lon0, lon1, lat0, lat1); EDGES add a slanted or patterned cut to a
# rectangle, as (box, mode, a, b, c):
#   roof:     inside if lat <  a - (lon - b) * c
#   floor:    inside if lat >  a + (lon - b) * c
#   absroof:  inside if lat <  a - abs(lon - b) * c
#   absfloor: inside if lat >  a + abs(lon - b) * c
#   lonmax:   inside if lon <  a + lat * c
#   mod3:     inside if (lon + lat) % 3 != 0     (broken coastlines)
#   mod4:     inside if int(lon) % 4 != 0       (island chains)
#   nzdiag:   inside if abs((lon - a) - (-lat - b)) < 4

PLAIN_BOXES = [
    (-168, -140, 55, 70), (-125, -67, 25, 49), (-92, -77, 7, 18),
    (-77, -35, -5, 10), (-70, -40, -20, -5), (-73, -67, -55, -40),
    (-9, 3, 36, 44), (-5, 30, 45, 55), (30, 45, 45, 65),
    (-17, 32, 15, 35), (-17, 20, 4, 15), (8, 42, -5, 5),
    (43, 50, -25, -12),
    (35, 63, 12, 42), (45, 90, 35, 55), (92, 108, 5, 28),
    (75, 135, 18, 53),
    (113, 142, -22, -11), (115, 150, -39, -25), (131, 147, -9, -1),
]

EDGES = [
    ((-140, -60, 42, 72), "roof", 68, -60, 0.05),      # Canada
    ((-117, -87, 14, 32), "floor", 10, -117, 0.12),    # Mexico
    ((-58, -20, 60, 82), "absroof", 84, -39, 0.35),    # Greenland
    ((-73, -55, -40, -20), "lonmax", -71, 0, -0.4),    # South America
    ((5, 31, 55, 70), "absroof", 72, 18, 0.25),        # Scandinavia
    ((12, 35, -35, -5), "lonmax", 38, 0, 0.35),        # southern Africa
    ((60, 178, 50, 75), "roof", 78, 60, 0.06),         # Siberia
    ((68, 89, 8, 35), "absfloor", 4, 78, 0.9),         # India
    ((126, 142, 31, 45), "mod3", 0, 0, 0),             # Korea / Japan
    ((95, 141, -10, 5), "mod4", 0, 0, 0),              # Indonesia
    ((167, 178, -46, -34), "nzdiag", 167, 34, 0),      # New Zealand
]


def _inside(lon, lat, box):
    return box[0] <= lon <= box[1] and box[2] <= lat <= box[3]


def land(lon, lat):
    if any(_inside(lon, lat, b) for b in PLAIN_BOXES):
        return True
    for box, mode, a, b, c in EDGES:
        if not _inside(lon, lat, box):
            continue
        if mode == "roof" and lat < a - (lon - b) * c:
            return True
        if mode == "floor" and lat > a + (lon - b) * c:
            return True
        if mode == "absroof" and lat < a - abs(lon - b) * c:
            return True
        if mode == "absfloor" and lat > a + abs(lon - b) * c:
            return True
        if mode == "lonmax" and lon < a + lat * c:
            return True
        if mode == "mod3" and (lon + lat) % 3 != 0:
            return True
        if mode == "mod4" and int(lon) % 4 != 0:
            return True
        if mode == "nzdiag" and abs((lon - a) - (-lat - b)) < 4:
            return True
    return False


# Story pins 1-13: (number, longitude, latitude, place)
PINS = [
    (1, 114.0, 22.5, "Shenzhen"),
    (2, 34.3, 31.4, "Gaza"),
    (3, -77.0, 38.9, "Washington"),
    (4, -122.4, 37.8, "San Francisco"),
    (5, 36.6, 45.0, "Kerch"),
    (6, -87.6, 41.9, "Chicago"),
    (7, 149.0, -35.4, "Canberra"),
    (8, 4.9, 52.4, "Amsterdam"),
    (9, 30.7, 36.9, "Antalya"),
    (10, 139.7, 35.7, "Tokyo"),
    (11, 14.4, 50.1, "Prague"),
    (12, 85.1, 19.8, "Odisha"),
    (13, 174.8, -36.8, "Auckland"),
]


def world_map(pg):
    pg.draw("bold14", MARGIN, 610, "WHERE IT HAPPENED", INK)
    pg.draw_r("reg10", MARGIN + WIDTH, 614,
              "Shenzhen · Gaza · Washington · Kerch · Chicago · "
              "Antalya · Tokyo · Prague · Auckland", FAINT)
    cols, rows = 118, 28
    x0, y0 = MARGIN + 22, 642
    lons = [-170 + 3.05 * c for c in range(cols)]
    lats = [75 - 4.5 * r for r in range(rows)]
    for r, lat in enumerate(lats):
        for c, lon in enumerate(lons):
            if land(lon, lat):
                pg.disc(x0 + c * 8, y0 + r * 5, 2, MAPDOT)
    for num, lon, lat, _place in PINS:
        px = x0 + round((lon + 170) / 3.05) * 8
        py = y0 + round((75 - lat) / 4.5) * 5
        pg.disc(px, py, 11, PAPER)  # halo keeps close pins readable
        pg.disc(px, py, 9, RED)
        label = str(num)
        pg.draw("bold10", px - measure("bold10", label) // 2,
                py - 6, label, WHITE)


# ------------------------------------------------------------------ briefs

def briefs_block(pg):
    pg.fill(MARGIN, 786, WIDTH, 2, INK)
    pg.draw("bold14", MARGIN, 794, "ALSO ON THURSDAY 19 NOVEMBER", INK)
    pg.draw_r("reg11", MARGIN + WIDTH, 797, "STORIES 14–38", FAINT)
    groups = [(0, BRIEFS[0:9]), (332, BRIEFS[9:17]), (664, BRIEFS[17:25])]
    n = 14
    for x_off, items in groups:
        yy = 800
        for item in items:
            yy += 18
            pg.draw("bold12", MARGIN + x_off, yy - 1, str(n) + ".", RED)
            pg.draw("reg11", MARGIN + x_off + 24, yy, item, BODY)
            n += 1
    pg.fill(MARGIN, 984, WIDTH, 1, BORDER)
    pg.draw("reg11", MARGIN, 990,
            "Every story was reported on Thursday 19 November 2026", FAINT)
    pg.draw_r("reg11", MARGIN + WIDTH, 990,
              "Sources: Reuters · AP · BBC · Al Jazeera · CNN · "
              "UN News · NASA · Sotheby's", FAINT)


# ------------------------------------------------------------------ main

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    FONTS.update(read_fonts(os.path.join(here, "fonts.bin")))
    page = Page(1024, PAPER)
    for section in (header_block, lead_row, grid_block, world_map,
                    briefs_block):
        section(page)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    size = save_png(page, os.path.join(out_dir, "entry.png"))
    print("entry.png:", size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
