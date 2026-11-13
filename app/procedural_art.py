"""Offline procedural scene illustration fallback (not generative AI)."""
import hashlib
import random
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter

PALETTES = {
    "water": ((3, 18, 39), (10, 88, 112), (35, 139, 151), (210, 198, 155)),
    "forest": ((4, 22, 25), (20, 72, 54), (63, 111, 72), (215, 180, 111)),
    "desert": ((43, 23, 29), (130, 65, 46), (203, 128, 71), (250, 202, 126)),
    "city": ((7, 12, 31), (34, 43, 76), (83, 79, 110), (255, 181, 111)),
    "temple": ((17, 12, 28), (72, 39, 54), (145, 83, 66), (246, 190, 119)),
    "space": ((2, 4, 22), (22, 18, 65), (67, 50, 115), (165, 180, 255)),
    "default": ((5, 10, 28), (34, 45, 83), (91, 112, 153), (235, 194, 126)),
}

def _scene_palette(prompt):
    p = prompt.casefold()
    terms = {
        "water": ("ocean", "sea", "river", "lake", "समुद्र", "समंदर", "नदी", "झील"),
        "forest": ("forest", "jungle", "woods", "जंगल", "वन"),
        "desert": ("desert", "sand", "रेगिस्तान", "मरुस्थल"),
        "city": ("city", "street", "urban", "शहर", "सड़क"),
        "temple": ("temple", "fort", "palace", "mandir", "मंदिर", "किला", "महल"),
        "space": ("space", "galaxy", "planet", "अंतरिक्ष", "ग्रह"),
    }
    for name, words in terms.items():
        if any(word in p for word in words):
            return name
    return "default"

def generate_procedural_scene_bytes(prompt: str, width: int, height: int) -> bytes:
    """Create a deterministic text-free cinematic illustration for offline storyboards."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 3000:
        raise ValueError("Scene prompt must contain 1 to 3000 characters.")
    if not isinstance(width, int) or not isinstance(height, int) or not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Scene image dimensions must be between 256 and 2048 pixels.")
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    palette = PALETTES[_scene_palette(prompt)]
    top, mid, low, glow = palette
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        a, b, f = (top, mid, t / .62) if t < .62 else (mid, low, (t - .62) / .38)
        color = tuple(int(a[i] * (1-f) + b[i] * f) for i in range(3))
        for x in range(width):
            pixels[x, y] = color
    light = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)
    cx, cy = int(width * (.3 + rng.random() * .4)), int(height * .25)
    radius = int(min(width, height) * .11)
    for scale, alpha in ((2.5, 12), (1.7, 22), (1, 190)):
        r = int(radius * scale)
        ld.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(*glow, alpha))
    light = light.filter(ImageFilter.GaussianBlur(max(3, radius // 3)))
    image = Image.alpha_composite(image.convert("RGBA"), light)
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(max(30, width * height // 20000)):
        x, y = rng.randrange(width), rng.randrange(int(height * .68))
        r = rng.choice((1, 1, 2))
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(255, 245, 220, rng.randrange(65, 175)))
    kind = _scene_palette(prompt)
    horizon = int(height * .70)
    if kind == "water":
        draw.rectangle((0, horizon, width, height), fill=(2, 24, 43, 205))
        for i in range(30):
            y = horizon + i * max(2, (height-horizon)//32)
            x = rng.randrange(width)
            draw.line((x, y, min(width, x+rng.randrange(20, max(21, width//2))), y),
                      fill=(145, 211, 210, rng.randrange(25, 100)), width=2)
        draw.polygon([(0,horizon),(int(width*.25),int(height*.49)),(int(width*.5),horizon)], fill=(8,35,53,230))
    elif kind in {"city", "temple"}:
        base = int(height * .88)
        x = 0
        while x < width:
            bw = rng.randrange(max(18,width//18), max(30,width//8))
            bh = rng.randrange(int(height*.14), int(height*.40))
            draw.rectangle((x,base-bh,min(width,x+bw),base), fill=(9,13,29,245))
            if kind == "city":
                for wx in range(x+5,min(width,x+bw-3),max(8,bw//4)):
                    for wy in range(base-bh+8,base-5,max(10,height//45)):
                        if rng.random() > .4:
                            draw.rectangle((wx,wy,wx+3,wy+5),fill=(255,190,112,165))
            x += bw
        if kind == "temple":
            c = width//2
            draw.rectangle((int(width*.27),int(height*.50),int(width*.73),base),fill=(34,21,31,250))
            draw.polygon([(int(width*.22),int(height*.51)),(c,int(height*.29)),(int(width*.78),int(height*.51))],fill=(55,31,40,250))
            draw.polygon([(int(width*.39),int(height*.50)),(c,int(height*.18)),(int(width*.61),int(height*.50))],fill=(75,40,47,245))
            draw.rectangle((int(width*.46),int(height*.70),int(width*.54),base),fill=(8,9,18,255))
    else:
        for layer, color in enumerate(((16,25,43,185),(8,18,34,225),(4,12,25,250))):
            base = int(height*(.72+layer*.09))
            points = [(0,base)]
            x = 0
            while x < width:
                x += rng.randrange(max(24,width//12),max(40,width//5))
                points.append((min(width,x),base-rng.randrange(int(height*.08),int(height*.28))))
            points.extend([(width,height),(0,height)])
            draw.polygon(points,fill=color)
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
