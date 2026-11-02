"""Small, bounded flag palette extraction for optional TUI accents."""
import colorsys
from io import BytesIO
import warnings
from PIL import Image

DEFAULT_ACCENT = "#67ded0"


def flag_accent(data):
    """Choose a dominant colorful accent, brightened for the dark UI."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError("Flag image is too large")
            image.thumbnail((64, 64))
            rgba = image.convert("RGBA")
            base = Image.new("RGBA", rgba.size, "#0b1220")
            base.alpha_composite(rgba)
            palette = base.convert("RGB").quantize(colors=8).convert("RGB")
            colors = palette.getcolors(4096) or []
    if not colors:
        return DEFAULT_ACCENT
    def weight(entry):
        count, rgb = entry
        _, light, saturation = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
        return count * (0.15 + saturation) * (0.2 if light < .08 or light > .93 else 1)
    _, rgb = max(colors, key=weight)
    hue, light, saturation = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    light = max(.65, min(light, .8))
    def luminance(channels):
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    background = luminance((11 / 255, 18 / 255, 32 / 255))
    while True:
        rgb = colorsys.hls_to_rgb(hue, light, saturation)
        if (luminance(rgb) + .05) / (background + .05) >= 4.5 or light >= .9:
            break
        light += .025
    return "#" + "".join(f"{round(v * 255):02x}" for v in rgb)
