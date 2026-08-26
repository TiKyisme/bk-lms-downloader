from __future__ import annotations

from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw


@lru_cache(maxsize=64)
def icon(name: str, color: str, size: int = 18) -> ctk.CTkImage:
    """Draw the small, consistent interface icons used by the light UI."""
    scale = 3
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    s = scale

    def xy(value: int) -> int:
        return value * s

    width = max(2, xy(1))
    if name == "chrome":
        draw.ellipse((xy(1), xy(1), xy(size - 1), xy(size - 1)), fill="#FBC02D")
        draw.pieslice((xy(1), xy(1), xy(size - 1), xy(size - 1)), 25, 145, fill="#EF5350")
        draw.pieslice((xy(1), xy(1), xy(size - 1), xy(size - 1)), 145, 265, fill="#43A047")
        draw.pieslice((xy(1), xy(1), xy(size - 1), xy(size - 1)), 265, 385, fill="#1E88E5")
        draw.ellipse((xy(5), xy(5), xy(size - 5), xy(size - 5)), fill="#FFFFFF")
        draw.ellipse((xy(6), xy(6), xy(size - 6), xy(size - 6)), fill="#1976D2")
    elif name == "check":
        draw.ellipse((xy(1), xy(1), xy(size - 1), xy(size - 1)), fill=color)
        draw.line((xy(5), xy(9), xy(8), xy(12), xy(14), xy(6)), fill="#FFFFFF", width=width)
    elif name == "info":
        draw.ellipse((xy(1), xy(1), xy(size - 1), xy(size - 1)), outline=color, width=width)
        draw.line((xy(size // 2), xy(8), xy(size // 2), xy(13)), fill=color, width=width)
        draw.ellipse((xy(size // 2 - 1), xy(4), xy(size // 2 + 1), xy(6)), fill=color)
    elif name == "cap":
        draw.polygon([(xy(1), xy(7)), (xy(9), xy(3)), (xy(17), xy(7)), (xy(9), xy(11))], outline=color, fill=None, width=width)
        draw.line((xy(4), xy(9), xy(4), xy(13), xy(9), xy(16), xy(14), xy(13), xy(14), xy(9)), fill=color, width=width)
        draw.line((xy(17), xy(7), xy(17), xy(13)), fill=color, width=width)
        draw.ellipse((xy(16), xy(13), xy(18), xy(15)), fill=color)
    elif name == "plus":
        draw.line((xy(9), xy(3), xy(9), xy(15)), fill=color, width=width)
        draw.line((xy(3), xy(9), xy(15), xy(9)), fill=color, width=width)
    elif name == "download":
        draw.line((xy(9), xy(2), xy(9), xy(11)), fill=color, width=width)
        draw.polygon([(xy(5), xy(9)), (xy(9), xy(13)), (xy(13), xy(9))], fill=color)
        draw.rounded_rectangle((xy(3), xy(14), xy(15), xy(17)), radius=xy(1), outline=color, width=width)
    elif name == "edit":
        draw.line((xy(4), xy(14), xy(5), xy(10), xy(13), xy(2), xy(16), xy(5), xy(8), xy(13), xy(4), xy(14)), fill=color, width=width)
    elif name == "trash":
        draw.line((xy(4), xy(5), xy(14), xy(5)), fill=color, width=width)
        draw.line((xy(7), xy(3), xy(11), xy(3)), fill=color, width=width)
        draw.rounded_rectangle((xy(5), xy(6), xy(13), xy(16)), radius=xy(1), outline=color, width=width)
        draw.line((xy(8), xy(8), xy(8), xy(14)), fill=color, width=width)
        draw.line((xy(10), xy(8), xy(10), xy(14)), fill=color, width=width)
    elif name == "folder":
        draw.rounded_rectangle((xy(2), xy(6), xy(16), xy(15)), radius=xy(2), outline=color, width=width)
        draw.rounded_rectangle((xy(3), xy(4), xy(9), xy(8)), radius=xy(1), outline=color, width=width)
    elif name == "tools":
        draw.ellipse((xy(2), xy(2), xy(8), xy(8)), outline=color, width=width)
        draw.line((xy(7), xy(7), xy(15), xy(15)), fill=color, width=width)
        draw.ellipse((xy(13), xy(13), xy(16), xy(16)), fill=color)
        draw.line((xy(12), xy(4), xy(16), xy(8)), fill=color, width=width)
    elif name == "sync":
        draw.arc((xy(2), xy(2), xy(16), xy(16)), 30, 205, fill=color, width=width)
        draw.arc((xy(2), xy(2), xy(16), xy(16)), 210, 385, fill=color, width=width)
        draw.polygon([(xy(14), xy(3)), (xy(17), xy(7)), (xy(12), xy(7))], fill=color)
        draw.polygon([(xy(4), xy(15)), (xy(1), xy(11)), (xy(6), xy(11))], fill=color)
    elif name == "chevron":
        draw.line((xy(5), xy(7), xy(9), xy(11), xy(13), xy(7)), fill=color, width=width)
    elif name == "brand":
        draw.polygon([(xy(9), xy(1)), (xy(16), xy(5)), (xy(16), xy(13)), (xy(9), xy(17)), (xy(2), xy(13)), (xy(2), xy(5))], fill="#0B6FFB")
        draw.polygon([(xy(9), xy(4)), (xy(14), xy(7)), (xy(9), xy(10)), (xy(4), xy(7))], fill="#FFFFFF")
        draw.line((xy(5), xy(10), xy(5), xy(13), xy(9), xy(15), xy(13), xy(13), xy(13), xy(10)), fill="#FFFFFF", width=width)
    else:
        draw.ellipse((xy(3), xy(3), xy(size - 3), xy(size - 3)), fill=color)

    rendered = canvas.resize((size, size), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=rendered, dark_image=rendered, size=(size, size))
