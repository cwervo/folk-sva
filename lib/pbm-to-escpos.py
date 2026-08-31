#!/usr/bin/env python3
"""Convert a binary PBM (P4) into an ESC/POS raster job.

Ghostscript's pbmraw device already emits exactly what ESC/POS raster
mode wants: rows of packed 1-bit pixels, MSB first, rows padded out to a
byte boundary, and 1 meaning "black". So there is no bit twiddling to do
here -- we only have to slice the image into bands and put a header on
each one.

Usage: pbm-to-escpos.py in.pbm out.escpos
"""
import sys

# Printers choke on a single enormous raster command, so emit the image
# in horizontal bands.
BAND_ROWS = 128


def read_pbm(path):
    with open(path, "rb") as f:
        data = f.read()

    if not data.startswith(b"P4"):
        raise SystemExit("not a binary PBM (P4): %s" % path)

    # Parse the header: magic, width, height -- skipping whitespace and
    # comments, which may appear between any two tokens.
    pos = 2
    fields = []
    while len(fields) < 2:
        while pos < len(data) and data[pos : pos + 1].isspace():
            pos += 1
        if data[pos : pos + 1] == b"#":
            while pos < len(data) and data[pos] != 0x0A:
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos : pos + 1].isspace():
            pos += 1
        fields.append(int(data[start:pos]))
    pos += 1  # exactly one whitespace byte follows the header

    width, height = fields
    row_bytes = (width + 7) // 8
    expected = row_bytes * height
    raster = data[pos : pos + expected]
    if len(raster) < expected:
        raise SystemExit(
            "truncated PBM: wanted %d bytes of raster, got %d"
            % (expected, len(raster))
        )
    return width, height, row_bytes, raster


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    width, height, row_bytes, raster = read_pbm(sys.argv[1])

    out = bytearray()
    out += b"\x1b\x40"  # ESC @  -- reset

    for top in range(0, height, BAND_ROWS):
        rows = min(BAND_ROWS, height - top)
        # GS v 0 m xL xH yL yH : m=0 normal, x in BYTES, y in dots.
        out += b"\x1d\x76\x30\x00"
        out += bytes((row_bytes & 0xFF, (row_bytes >> 8) & 0xFF))
        out += bytes((rows & 0xFF, (rows >> 8) & 0xFF))
        out += raster[top * row_bytes : (top + rows) * row_bytes]

    out += b"\x1b\x64\x04"  # feed 4 lines clear of the tear bar
    out += b"\x1d\x56\x00"  # full cut

    with open(sys.argv[2], "wb") as f:
        f.write(out)

    sys.stderr.write(
        "%dx%d dots, %d bytes/row, %d bands, %d bytes ESC/POS\n"
        % (width, height, row_bytes, (height + BAND_ROWS - 1) // BAND_ROWS, len(out))
    )


if __name__ == "__main__":
    main()
