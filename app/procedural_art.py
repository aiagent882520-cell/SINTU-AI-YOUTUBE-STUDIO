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

def _fort_shot(prompt: str) -> str:
    """Select a distinct documentary composition from the requested camera shot."""
    p = prompt.casefold()
    if any(w in p for w in ("close detail", "carving", "texture", "नक्काशी")): return "detail"
    if any(w in p for w in ("interior", "passage", "corridor", "गलियारा")): return "interior"
    if any(w in p for w in ("low-angle", "low angle", "monumental")): return "low"
    if any(w in p for w in ("aerial", "bird", "overhead")): return "aerial"
    if any(w in p for w in ("side-angle", "side angle", "rampart", "wall", "प्राचीर")): return "wall"
    if any(w in p for w in ("sunset", "silhouette", "dusk")): return "silhouette"
    return "wide"


def _draw_fort_shot(draw, width: int, height: int, shot: str, rng) -> None:
    """Draw different fort architecture for each shot; still procedural art, not AI."""
    stone, lit, dark = (91, 58, 49, 255), (183, 125, 79, 230), (12, 12, 20, 255)
    if shot == "detail":
        draw.rectangle((0, int(height*.28), width, height), fill=(49,35,39,255))
        bh = max(24, height//12)
        for y in range(int(height*.28), height, bh):
            offset = (y//bh%2)*(width//8)
            for x in range(-offset,width,width//4):
                draw.rectangle((x+3,y+3,x+width//4-4,y+bh-4),fill=stone,outline=lit,width=2)
        cx,cy,r=width//2,int(height*.53),min(width,height)//7
        draw.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(224,174,112,230),width=max(3,width//90))
        for a in range(0,360,45):
            import math
            x=int(cx+math.cos(math.radians(a))*r*.72); y=int(cy+math.sin(math.radians(a))*r*.72)
            draw.ellipse((x-r//7,y-r//7,x+r//7,y+r//7),fill=lit)
    elif shot == "interior":
        draw.rectangle((0,0,width,height),fill=(13,12,22,255))
        draw.polygon([(0,0),(int(width*.28),int(height*.18)),(int(width*.28),height),(0,height)],fill=stone)
        draw.polygon([(width,0),(int(width*.72),int(height*.18)),(int(width*.72),height),(width,height)],fill=(62,39,39,255))
        draw.polygon([(int(width*.28),int(height*.18)),(int(width*.72),int(height*.18)),(int(width*.55),height),(int(width*.45),height)],fill=(183,119,70,95))
        for y in (int(height*.25),int(height*.43),int(height*.65)):
            draw.arc((int(width*.18),y-int(height*.18),int(width*.82),y+int(height*.28)),180,360,fill=lit,width=4)
        draw.rectangle((int(width*.46),int(height*.46),int(width*.54),height),fill=dark)
    elif shot == "aerial":
        draw.polygon([(0,int(height*.78)),(int(width*.18),int(height*.48)),(int(width*.48),int(height*.34)),(int(width*.82),int(height*.5)),(width,int(height*.82)),(width,height),(0,height)],fill=(18,31,34,255))
        for cx,cy,rx,ry in ((.5,.48,.29,.16),(.32,.57,.12,.07),(.69,.59,.13,.08)):
            draw.ellipse((int(width*(cx-rx)),int(height*(cy-ry)),int(width*(cx+rx)),int(height*(cy+ry))),fill=stone,outline=lit,width=4)
        draw.line([(0,int(height*.82)),(int(width*.18),int(height*.55)),(int(width*.48),int(height*.40)),(int(width*.82),int(height*.57)),(width,int(height*.86))],fill=lit,width=max(8,width//28))
    elif shot == "wall":
        draw.polygon([(0,int(height*.48)),(width,int(height*.25)),(width,int(height*.67)),(0,int(height*.86))],fill=stone)
        draw.polygon([(0,int(height*.45)),(width,int(height*.22)),(width,int(height*.29)),(0,int(height*.53))],fill=lit)
        for i in range(13):
            x=int(width*i/12); y=int(height*(.43-.20*i/12))
            draw.rectangle((x,y-max(12,height//35),x+max(8,width//35),y+height//12),fill=dark)
    elif shot == "low":
        draw.polygon([(0,height),(int(width*.12),int(height*.20)),(int(width*.36),int(height*.10)),(int(width*.49),height)],fill=stone)
        draw.polygon([(width,height),(int(width*.88),int(height*.20)),(int(width*.64),int(height*.10)),(int(width*.51),height)],fill=(65,42,43,255))
        draw.rectangle((int(width*.36),int(height*.26),int(width*.64),height),fill=(105,66,51,255))
        for y in range(int(height*.30),int(height*.78),max(30,height//12)):
            draw.line((int(width*.37),y,int(width*.63),y),fill=lit,width=3)
    else:
        base=int(height*.87)
        draw.rectangle((int(width*.13),int(height*.48),int(width*.87),base),fill=stone,outline=lit,width=4)
        draw.polygon([(int(width*.10),int(height*.50)),(int(width*.5),int(height*.25)),(int(width*.90),int(height*.50))],fill=dark)
        for x in (int(width*.16),int(width*.72)):
            draw.rectangle((x,int(height*.32),x+int(width*.12),base),fill=(71,45,42,255),outline=lit,width=3)
        draw.ellipse((int(width*.42),int(height*.62),int(width*.58),int(height*.92)),fill=dark,outline=lit,width=3)
        draw.rectangle((int(width*.42),int(height*.78),int(width*.58),base),fill=dark)


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
    gradient = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        a, b, f = (top, mid, t / .62) if t < .62 else (mid, low, (t - .62) / .38)
        color = tuple(int(a[i] * (1-f) + b[i] * f) for i in range(3))
        gradient.line((0, y, width, y), fill=color)
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
    elif kind == "temple":
        _draw_fort_shot(draw, width, height, _fort_shot(prompt), rng)
    elif kind == "city":
        base = int(height * .88)
        x = 0
        while x < width:
            bw = rng.randrange(max(18,width//18), max(30,width//8))
            bh = rng.randrange(int(height*.14), int(height*.40))
            draw.rectangle((x,base-bh,min(width,x+bw),base), fill=(9,13,29,245))
            for wx in range(x+5,min(width,x+bw-3),max(8,bw//4)):
                for wy in range(base-bh+8,base-5,max(10,height//45)):
                    if rng.random() > .4:
                        draw.rectangle((wx,wy,wx+3,wy+5),fill=(255,190,112,165))
            x += bw
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
