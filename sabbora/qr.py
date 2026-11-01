"""Minimal QR code encoder (byte mode, error-correction level M, versions 1-10).

Enough for the short join links Sabbora shows; written from the QR specification
so the program needs no extra package. qr_matrix(text) -> list of rows of bools.
"""

# Level M tables for versions 1..10: (ECC codewords per block, number of blocks)
_ECC_M = {1: (10, 1), 2: (16, 1), 3: (26, 1), 4: (18, 2), 5: (24, 2),
          6: (16, 4), 7: (18, 4), 8: (22, 4), 9: (22, 5), 10: (26, 5)}
_FORMAT_M = 0          # level M format bits


def _raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    ecc, blocks = _ECC_M[ver]
    return _raw_modules(ver) // 8 - ecc * blocks


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(result)):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < len(result):
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _alignment_positions(ver):
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    size = ver * 4 + 17
    result = [size - 7 - i * step for i in range(n - 1)] + [6]
    return sorted(result)


class _Grid:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.mod[y][x] = dark
        self.fn[y][x] = True

    def draw_function_patterns(self):
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set_fn(a, b, bit)
                self.set_fn(b, a, bit)

    def draw_format(self, mask):
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        n = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)

    def draw_codewords(self, data):
        n, i = self.size, 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < len(data) * 8:
                        self.mod[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        f = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self):
        """Simplified ISO penalty (runs, 2x2 blocks, balance) to pick a readable mask."""
        n, m, score = self.size, self.mod, 0
        for rows in (m, [list(col) for col in zip(*m)]):
            for row in rows:
                run, prev = 0, None
                for v in row:
                    if v == prev:
                        run += 1
                        if run == 5:
                            score += 3
                        elif run > 5:
                            score += 1
                    else:
                        run, prev = 1, v
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(r) for r in m)
        score += abs(dark * 20 - n * n * 10) // (n * n) * 10
        return score


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def qr_matrix(text):
    data = text.encode("utf-8")
    for ver in range(1, 11):
        cc_bits = 8 if ver <= 9 else 16
        if 4 + cc_bits + 8 * len(data) <= _data_codewords(ver) * 8:
            break
    else:
        raise ValueError("text too long for this QR encoder")
    cap = _data_codewords(ver) * 8
    bits = []

    def put(val, n):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)
    put(len(data), cc_bits)
    for b in data:
        put(b, 8)
    put(0, min(4, cap - len(bits)))
    put(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    ecc_len, nblocks = _ECC_M[ver]
    raw = _raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = codewords[k:k + short_len - ecc_len + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    final = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= nshort:
                final.append(blk[i])

    best, best_score = None, None
    for mask in range(8):
        g = _Grid(ver)
        g.draw_function_patterns()
        g.draw_codewords(final)
        g.apply_mask(mask)
        g.draw_format(mask)
        score = g.penalty()
        if best_score is None or score < best_score:
            best, best_score = g, score
    return best.mod


def qr_pixmap(text, scale=8, border=4, dark="#0F172A", light="#FFFFFF"):
    from PyQt5.QtGui import QColor, QPainter, QPixmap
    m = qr_matrix(text)
    n = len(m)
    size = (n + 2 * border) * scale
    pm = QPixmap(size, size)
    pm.fill(QColor(light))
    p = QPainter(pm)
    p.setPen(QColor(dark))
    p.setBrush(QColor(dark))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.fillRect((x + border) * scale, (y + border) * scale, scale, scale, QColor(dark))
    p.end()
    return pm


def qr_image(text, scale=8, border=4):
    """PIL image (used by tests)."""
    from PIL import Image
    m = qr_matrix(text)
    n = len(m)
    img = Image.new("L", ((n + 2 * border) * scale,) * 2, 255)
    px = img.load()
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                for dy in range(scale):
                    for dx in range(scale):
                        px[(x + border) * scale + dx, (y + border) * scale + dy] = 0
    return img
