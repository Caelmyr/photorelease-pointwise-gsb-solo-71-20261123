from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from image_lab.codecs import decode_image
from image_lab.validation import Invalid

from . import model


MAX_INPUT_BYTES = 24 * 1024 * 1024
INPUT_FORMATS = {"JPEG", "PNG", "WEBP", "TIFF"}
SHEET_BACKGROUND = "#e7e5de"
SHEET_PAGE_LIMIT = 6


def encode(image, format_name="png"):
    # Rebuild the pixel-bearing object so encoder metadata cannot follow the source.
    clean = Image.frombytes("RGB", image.size, image.convert("RGB").tobytes())
    target = BytesIO()
    if format_name == "jpg":
        clean.save(target, "JPEG", quality=92, subsampling=0, optimize=True)
    else:
        clean.save(target, "PNG", compress_level=4)
    return target.getvalue()


def open_bytes(payload):
    with Image.open(BytesIO(payload)) as image:
        return image.convert("RGB")


def source_name(filename):
    return Path(filename or "Untitled").stem.strip()[:100] or "Untitled"


def from_upload(blobs, raw, filename):
    if len(raw) > MAX_INPUT_BYTES:
        raise Invalid("A source image must be 24 MB or less.")
    try:
        with Image.open(BytesIO(raw)) as candidate:
            if candidate.format not in INPUT_FORMATS or candidate.n_frames != 1:
                raise Invalid("Choose a single-frame PNG, JPEG, WebP or TIFF.")
    except (OSError, Image.DecompressionBombError) as error:
        raise Invalid("The selected file could not be read as a supported photograph.") from error
    pixels, _ = decode_image(raw)
    image = Image.fromarray(np.rint(pixels * 255).astype(np.uint8), "RGB")
    working = blobs.put(encode(image))
    return model.photo_record(source_name(filename), image.size, working, blobs.put(raw), provenance="upload")


def from_preparation(blobs, pixels, origin, name, provenance):
    image = Image.fromarray(np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8), "RGB")
    working = blobs.put(encode(image))
    return model.photo_record(name[:100], image.size, working, None, provenance=provenance, origin=origin)


def extent(photo):
    return photo["style"]["crop"] or [0, 0, photo["width"], photo["height"]]


def overlap(box, crop):
    x0, y0 = max(box[0], crop[0]), max(box[1], crop[1])
    x1, y1 = min(box[2], crop[2]), min(box[3], crop[3])
    return [x0, y0, x1, y1] if x0 < x1 and y0 < y1 else None


def area(box):
    return (box[2] - box[0]) * (box[3] - box[1]) if box else 0


def output_size(crop, style):
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    scale = min(1, model.EXPORT_EDGES[style["edge"]] / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def crop_review(photo):
    crop = extent(photo)
    entries = []
    for mark in photo["marks"]:
        intersection = overlap(mark["box"], crop)
        fraction = area(intersection) / area(mark["box"])
        entries.append({
            "id": mark["id"], "kind": mark["kind"], "label": mark["label"],
            "state": "outside" if fraction == 0 else ("inside" if fraction == 1 else "clipped"),
            "fraction": fraction,
        })
    return {"crop": crop, "size": output_size(crop, photo["style"]), "marks": entries}


def working_image(blobs, photo, edge=None):
    image = open_bytes(blobs.read(photo["working"]))
    if edge:
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return image


def create_rendition(blobs, photo):
    image = working_image(blobs, photo)
    crop = extent(photo)
    color = ImageColor.getrgb(model.COVER_COLORS[photo["style"]["cover"]])
    draw = ImageDraw.Draw(image)
    for mark in photo["marks"]:
        if mark["kind"] == "cover":
            x0, y0, x1, y1 = mark["box"]
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=color)
    image = image.crop(tuple(crop))
    size = output_size(crop, photo["style"])
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def visible_difference(first, second):
    if first.size != second.size:
        raise Invalid("Pixel differences require issues with the same image dimensions.")
    a, b = np.asarray(first, dtype=np.int16), np.asarray(second, dtype=np.int16)
    delta = np.abs(a - b).max(axis=-1)
    highlighted = np.zeros((*delta.shape, 3), dtype=np.uint8)
    highlighted[:] = (29, 28, 36)
    changed = delta > 0
    highlighted[changed, 0] = np.minimum(255, 85 + delta[changed] * 4)
    highlighted[changed, 1] = 76
    highlighted[changed, 2] = 84
    report = {
        "changed_pixels": int(np.count_nonzero(changed)), "total_pixels": int(delta.size),
        "maximum_channel_delta": int(delta.max()),
    }
    return Image.fromarray(highlighted), report


def sheet_pages(items):
    for offset in range(0, len(items), SHEET_PAGE_LIMIT):
        yield items[offset:offset + SHEET_PAGE_LIMIT]


def sheet_page(items, title, page=1):
    width, tile_w, tile_h = 1080, 320, 238
    header, footer, gap = 102, 54, 22
    rows = (len(items) + 2) // 3
    height = header + rows * (tile_h + gap) + footer
    page_image = Image.new("RGB", (width, height), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(page_image)
    heading = ImageFont.load_default(size=28)
    body = ImageFont.load_default(size=15)
    draw.text((38, 28), title, fill="#26262d", font=heading)
    draw.text((40, 67), "PHOTO CONTACT SHEET", fill="#545463", font=body)
    for index, (image, caption) in enumerate(items):
        row, column = divmod(index, 3)
        x, y = 38 + column * (tile_w + gap), header + row * (tile_h + gap)
        draw.rectangle((x, y, x + tile_w, y + tile_h), fill="#f9f8f3")
        displayed = image.copy()
        displayed.thumbnail((tile_w - 16, tile_h - 58), Image.Resampling.LANCZOS)
        page_image.paste(displayed, (x + (tile_w - displayed.width) // 2, y + 9 + (tile_h - 58 - displayed.height) // 2))
        _place_caption(draw, caption, body, x + 10, y + tile_h - 40, tile_w - 20)
    draw.text((40, height - 36), f"Page {page:02d}", fill="#545463", font=body)
    return page_image


def _place_caption(draw, caption, font, x, y, width):
    remaining = caption.strip()
    for line in range(2):
        if not remaining:
            return
        take = len(remaining)
        while take > 0 and draw.textlength(remaining[:take], font=font) > width:
            take -= 1
        if take < len(remaining) and line == 0:
            split = remaining.rfind(" ", 0, take + 1)
            if split > 0:
                take = split
        bit = remaining[:take]
        if line == 1 and take < len(remaining):
            while bit and draw.textlength(bit + "…", font=font) > width:
                bit = bit[:-1]
            bit += "…"
        draw.text((x, y + line * 17), bit, font=font, fill="#26262d")
        remaining = remaining[take:].lstrip()
