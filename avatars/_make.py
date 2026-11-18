"""Ritar de tolv färdiga spelarbilderna. Körs en gång, bilderna sparas bredvid."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent
S = 512


def canvas():
    im = Image.new("RGB", (S, S), "#F4F1DE")
    d = ImageDraw.Draw(im)
    d.ellipse((28, 28, S - 28, S - 28), fill="#1B4D38")
    return im, d


def finish(im, name):
    im.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / f"{name}.png", "PNG")


def dice():
    im, d = canvas()
    d.rounded_rectangle((146, 146, 366, 366), radius=36, fill="#E63946")
    for x, y in ((196, 196), (316, 196), (256, 256), (196, 316), (316, 316)):
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill="#F4F1DE")
    finish(im, "dice")


def cat():
    im, d = canvas()
    d.polygon([(150, 230), (188, 110), (250, 200)], fill="#E07A3D")
    d.polygon([(362, 230), (324, 110), (262, 200)], fill="#E07A3D")
    d.ellipse((150, 168, 362, 380), fill="#E07A3D")
    d.ellipse((196, 230, 236, 278), fill="#F4F1DE")
    d.ellipse((276, 230, 316, 278), fill="#F4F1DE")
    d.ellipse((206, 244, 226, 268), fill="#133A2C")
    d.ellipse((286, 244, 306, 268), fill="#133A2C")
    d.polygon([(256, 286), (242, 308), (270, 308)], fill="#F4A3B5")
    finish(im, "cat")


def boat():
    im, d = canvas()
    d.polygon([(256, 128), (196, 300), (316, 300)], fill="#F4F1DE")
    d.polygon([(168, 308), (344, 308), (312, 372), (200, 372)], fill="#E63946")
    d.rectangle((248, 150, 264, 308), fill="#C6A35A")
    finish(im, "boat")


def crown():
    im, d = canvas()
    d.polygon(
        [(140, 340), (140, 210), (196, 270), (256, 150), (316, 270), (372, 210), (372, 340)],
        fill="#C6A35A",
    )
    d.rectangle((140, 328, 372, 368), fill="#C6A35A")
    d.ellipse((236, 214, 276, 254), fill="#E63946")
    finish(im, "crown")


def fox():
    im, d = canvas()
    d.polygon([(150, 250), (176, 120), (230, 210)], fill="#E07A3D")
    d.polygon([(362, 250), (336, 120), (282, 210)], fill="#E07A3D")
    d.ellipse((156, 180, 356, 390), fill="#E07A3D")
    d.ellipse((196, 250, 316, 370), fill="#F4F1DE")
    d.ellipse((210, 236, 242, 272), fill="#133A2C")
    d.ellipse((270, 236, 302, 272), fill="#133A2C")
    d.ellipse((240, 286, 272, 314), fill="#133A2C")
    finish(im, "fox")


def owl():
    im, d = canvas()
    d.ellipse((150, 140, 362, 390), fill="#C6A35A")
    d.polygon([(150, 210), (118, 150), (210, 180)], fill="#C6A35A")
    d.polygon([(362, 210), (394, 150), (302, 180)], fill="#C6A35A")
    d.ellipse((176, 210, 252, 300), fill="#F4F1DE")
    d.ellipse((260, 210, 336, 300), fill="#F4F1DE")
    d.ellipse((198, 236, 230, 274), fill="#133A2C")
    d.ellipse((282, 236, 314, 274), fill="#133A2C")
    d.polygon([(256, 286), (240, 312), (272, 312)], fill="#E07A3D")
    finish(im, "owl")


def mushroom():
    im, d = canvas()
    d.rounded_rectangle((220, 250, 292, 390), radius=16, fill="#F4F1DE")
    d.ellipse((140, 150, 372, 300), fill="#E63946")
    for x, y in ((190, 210), (256, 176), (320, 214)):
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill="#F4F1DE")
    finish(im, "mushroom")


def star():
    im, d = canvas()
    pts = []
    import math
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        r = 150 if i % 2 == 0 else 64
        pts.append((256 + r * math.cos(ang), 262 + r * math.sin(ang)))
    d.polygon(pts, fill="#C6A35A")
    finish(im, "star")


def fish():
    im, d = canvas()
    d.polygon([(168, 256), (118, 190), (118, 322)], fill="#3D8FD1")
    d.ellipse((150, 176, 390, 336), fill="#3D8FD1")
    d.ellipse((300, 230, 332, 262), fill="#F4F1DE")
    d.ellipse((310, 240, 324, 254), fill="#133A2C")
    finish(im, "fish")


def moon():
    im, d = canvas()
    d.ellipse((150, 130, 370, 390), fill="#C6A35A")
    d.ellipse((210, 110, 430, 370), fill="#1B4D38")
    finish(im, "moon")


def flower():
    im, d = canvas()
    for ang in range(0, 360, 72):
        import math
        x = 256 + 70 * math.cos(math.radians(ang - 90))
        y = 256 + 70 * math.sin(math.radians(ang - 90))
        d.ellipse((x - 48, y - 48, x + 48, y + 48), fill="#E07A9A")
    d.ellipse((216, 216, 296, 296), fill="#C6A35A")
    finish(im, "flower")


def penguin():
    im, d = canvas()
    d.ellipse((160, 130, 352, 400), fill="#133A2C")
    d.ellipse((196, 210, 316, 390), fill="#F4F1DE")
    d.ellipse((196, 176, 236, 220), fill="#F4F1DE")
    d.ellipse((276, 176, 316, 220), fill="#F4F1DE")
    d.ellipse((206, 188, 226, 210), fill="#133A2C")
    d.ellipse((286, 188, 306, 210), fill="#133A2C")
    d.polygon([(256, 214), (240, 236), (272, 236)], fill="#E07A3D")
    finish(im, "penguin")


if __name__ == "__main__":
    for fn in (dice, cat, boat, crown, fox, owl, mushroom, star, fish, moon, flower, penguin):
        fn()
