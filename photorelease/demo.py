import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import images, model


SCENES = [
    {
        "name": "Bike repair at the blue workshop", "caption": "Volunteer bike repair at the Blue Workshop",
        "colors": ("#79a2a3", "#e8d4a3", "#315668", "#ee855e"),
        "heads": [(284, 304), (585, 300), (787, 325)],
        "nameplate": (885, 523, 1010, 568),
    },
    {
        "name": "Tool lending counter", "caption": "Tools ready for the Saturday lending table",
        "colors": ("#c59875", "#e0dbb9", "#697462", "#ba6578"),
        "heads": [(318, 323), (691, 279)],
        "nameplate": (746, 521, 874, 556),
    },
    {
        "name": "Courtyard opening", "caption": "Early visitors at the courtyard opening",
        "colors": ("#8f9da1", "#d8d1a2", "#4e617b", "#d78055"),
        "heads": [(279, 318), (523, 299), (922, 318)],
        "nameplate": (160, 544, 270, 580),
    },
]


def _person(draw, x, y, tint, hair):
    draw.ellipse((x - 35, y - 52, x + 34, y + 28), fill=hair)
    draw.polygon([(x - 70, y + 134), (x - 52, y + 51), (x - 23, y + 20), (x + 21, y + 24),
                  (x + 65, y + 54), (x + 88, y + 146)], fill=tint)
    draw.ellipse((x - 28, y - 38, x + 29, y + 26), fill="#d7976f")
    draw.pieslice((x - 35, y - 54, x + 34, y + 7), 176, 350, fill=hair)
    draw.ellipse((x - 15, y - 11, x - 10, y - 7), fill="#2d2635")
    draw.ellipse((x + 10, y - 11, x + 15, y - 7), fill="#2d2635")
    draw.arc((x - 8, y - 1, x + 10, y + 12), 0, 150, fill="#7d493f", width=2)


def workshop(scene, index):
    accent, wall, shade, shirt = scene["colors"]
    image = Image.new("RGB", (1120, 740), wall)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1120, 135), fill=shade)
    draw.rectangle((0, 124, 1120, 166), fill="#474b43")
    for column in range(-70, 1140, 198):
        draw.rectangle((column, 174, column + 146, 413), fill=accent)
        draw.line((column + 72, 174, column + 72, 414), fill="#435656", width=7)
        draw.line((column, 314, column + 146, 314), fill="#435656", width=7)
        draw.polygon([(column + 6, 182), (column + 31, 182), (column + 144, 342),
                      (column + 142, 385)], fill="#abbfb7")
    draw.polygon([(0, 444), (1120, 437), (1120, 740), (0, 740)], fill="#9b8b72")
    draw.polygon([(0, 525), (1120, 488), (1120, 519), (0, 560)], fill="#615c50")
    draw.rectangle((43, 218, 149, 288), fill="#dddcbf")
    draw.text((52, 231), "OPEN", fill="#343137", font=ImageFont.load_default(size=24))
    colors = (shirt, shade, "#b3a055")
    for position, (x, y) in enumerate(scene["heads"]):
        _person(draw, x, y, colors[position], ("#352b2d", "#4a3835", "#40393d")[position])
    for column in range(112 + index * 27, 1095, 249):
        draw.ellipse((column, 510, column + 143, 652), outline="#333942", width=9)
        cx, cy = column + 71, 581
        draw.line((cx, 517, cx, 644), fill="#635f55", width=2)
        draw.line((cx - 64, cy, cx + 64, cy), fill="#635f55", width=2)
    x0, y0, x1, y1 = scene["nameplate"]
    draw.rectangle((x0, y0, x1, y1), fill="#ece7cc", outline="#393a43", width=3)
    draw.text((x0 + 8, y0 + 6), "B-07  SAMPLE", fill="#343137", font=ImageFont.load_default(size=14))
    pixels = np.asarray(image).astype(np.int16)
    noise = np.random.default_rng(index + 19).normal(0, 2.3, size=(*pixels.shape[:2], 1))
    return Image.fromarray(np.clip(pixels + noise, 0, 255).astype(np.uint8))


def create(library):
    desk = model.new_desk("Saturday workshop")
    for index, scene in enumerate(SCENES):
        image = workshop(scene, index)
        source = library.blobs.put(images.encode(image))
        photo = model.photo_record(scene["name"], image.size, source, None, provenance="synthetic")
        photo["style"]["caption"] = scene["caption"]
        for position, (x, y) in enumerate(scene["heads"]):
            data = {"box": [x - 36, y - 55, x + 37, y + 32]}
            if position == 0:
                data.update(kind="keep", label="Lead volunteer")
            else:
                data.update(kind="cover", label=f"Visitor {position}")
            model.new_mark(photo, data)
        model.new_mark(photo, {"box": list(scene["nameplate"]), "kind": "cover", "label": "Sample badge"})
        desk["photos"].append(photo)
    return library.add(desk)
