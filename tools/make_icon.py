"""Render assets/sabbora.ico with the same design as common.app_icon()."""
import os

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((S * .04, S * .10, S * .96, S * .80), radius=S * .10, fill="#9A6A3A")
d.rounded_rectangle((S * .11, S * .17, S * .89, S * .73), radius=S * .06, fill="#1E4D3A")
d.line([(S * .20, S * .62), (S * .36, S * .44), (S * .50, S * .54), (S * .70, S * .30)],
       fill="#F4F1E8", width=int(S * .055), joint="curve")
r = S * .07
d.ellipse((S * .70 - r, S * .30 - r, S * .70 + r, S * .30 + r), fill="#F2A541")
d.rectangle((S * .30, S * .80, S * .37, S * .94), fill="#9A6A3A")
d.rectangle((S * .63, S * .80, S * .70, S * .94), fill="#9A6A3A")
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sabbora.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
