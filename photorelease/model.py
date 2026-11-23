from datetime import datetime, timezone
import math
import re
from uuid import uuid4

from image_lab.validation import Invalid


MAX_PHOTOS = 24
MAX_MARKS = 40
MAX_ISSUES = 24
COVER_COLORS = {"ink": "#191923", "paper": "#eeebe1"}
MARK_TYPES = ("cover", "keep")
EXPORT_EDGES = {"screen": 1600, "web": 960, "small": 540}
FORMATS = {"png": "image/png", "jpg": "image/jpeg"}
JPEG_QUALITY_MAX = 92
JPEG_QUALITY_FLOOR = 40
PACKAGE_CAP_MIN = 512 * 1024
MANIFEST_NAME = "release.json"
RELEASE_SCHEMA = "photorelease-public-v1"
MAX_ARCHIVE = 96 * 1024 * 1024
KEY = re.compile(r"[0-9a-f]{32}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key():
    return uuid4().hex


def identifier(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise Invalid("This record identifier is invalid.")
    return value


def blob_id(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise Invalid("This file identifier is invalid.")
    return value


def text(value, name, limit, required=False):
    if not isinstance(value, str):
        raise Invalid(f"{name} must be text.")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise Invalid(f"{name} requires {'1–' if required else 'at most '}{limit} characters.")
    return value


def choice(value, options, name):
    if not isinstance(value, str) or value not in options:
        raise Invalid(f"Choose an available {name}.")
    return value


def integer(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise Invalid(f"{name} must be an integer from {lo} to {hi}.")
    return value


def select(records, target, name):
    identifier(target)
    for record in records:
        if record["id"] == target:
            return record
    raise Invalid(f"{name} was not found.")


def rectangle(data, width, height, name="Rectangle"):
    if not isinstance(data, list) or len(data) != 4:
        raise Invalid(f"{name} needs four coordinates.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in data):
        raise Invalid(f"{name} coordinates must be finite numbers.")
    x0, y0, x1, y1 = data
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise Invalid(f"{name} must have positive size and stay in the photograph.")
    return [math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)]


def default_style():
    return {
        "crop": None,
        "edge": "screen",
        "format": "png",
        "cover": "ink",
        "caption": "",
    }


def new_desk(title):
    stamp = now()
    return {
        "id": key(), "title": text(title, "Desk title", 90, True),
        "revision": 0, "created_at": stamp, "updated_at": stamp,
        "photos": [], "issues": [],
    }


def photo_record(name, dimensions, working, source, *, provenance, origin=None):
    width, height = dimensions
    return {
        "id": key(), "name": text(name, "Photo title", 100, True),
        "width": width, "height": height, "working": working, "source": source,
        "provenance": provenance, "origin": origin, "used": True, "approved": False,
        "style": default_style(), "marks": [],
    }


def change_style(photo, data):
    style = photo["style"]
    width, height = photo["width"], photo["height"]
    if "crop" in data:
        style["crop"] = None if data["crop"] is None else rectangle(data["crop"], width, height, "Crop")
    fields = (("edge", EXPORT_EDGES), ("format", FORMATS), ("cover", COVER_COLORS))
    for field, options in fields:
        if field in data:
            style[field] = choice(data[field], options, field)
    if "caption" in data:
        style["caption"] = text(data["caption"], "Public caption", 140)
    photo["approved"] = False


def new_mark(photo, data):
    if len(photo["marks"]) >= MAX_MARKS:
        raise Invalid(f"A photo can hold at most {MAX_MARKS} marks.")
    kind = choice(data.get("kind"), MARK_TYPES, "mark type")
    label = text(data.get("label", ""), "Mark label", 70)
    box = rectangle(data.get("box"), photo["width"], photo["height"], "Mark")
    mark = {"id": key(), "kind": kind, "label": label, "box": box}
    photo["marks"].append(mark)
    photo["approved"] = False
    return mark


def update_mark(photo, mark, data):
    if "label" in data:
        mark["label"] = text(data["label"], "Mark label", 70)
    if "box" in data:
        mark["box"] = rectangle(data["box"], photo["width"], photo["height"], "Mark")
    photo["approved"] = False


def summarize(desk):
    return {
        "id": desk["id"], "title": desk["title"], "updated_at": desk["updated_at"],
        "photo_count": len(desk["photos"]), "issue_count": len(desk["issues"]),
    }
