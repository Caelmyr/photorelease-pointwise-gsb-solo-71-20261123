from datetime import datetime, timezone
import math
import re
from uuid import uuid4

from image_lab.validation import Invalid


MAX_PHOTOS = 24
MAX_MARKS = 40
MAX_ISSUES = 24
MAX_BURST_HISTORY = 10
COVER_COLORS = {"ink": "#191923", "paper": "#eeebe1"}
MARK_TYPES = ("cover", "keep")
EXPORT_EDGES = {"screen": 1600, "web": 960, "small": 540}
FORMATS = {"png": "image/png", "jpg": "image/jpeg"}
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
        "photos": [], "issues": [], "burst_history": [],
    }


def photo_record(name, dimensions, working, source, *, provenance, origin=None):
    width, height = dimensions
    return {
        "id": key(), "name": text(name, "Photo title", 100, True),
        "width": width, "height": height, "working": working, "source": source,
        "provenance": provenance, "origin": origin, "used": True, "approved": False,
        "style": default_style(), "marks": [], "represented_by": None,
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


def apply_burst(desk, data):
    """Apply one reviewed grouping plan to the current draft only.

    Only photos in multi-photo groups change: the chosen representative stays
    selectable and every other member is unchecked with a back-reference.
    Saved issues are never touched.
    """
    mode = choice(data.get("mode"), ("anchor", "pairwise"), "grouping mode")
    threshold = integer(data.get("threshold"), "Similarity threshold", 0, 100)
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise Invalid("The grouping plan contains no groups.")
    plan = []
    seen = set()
    for entry in groups:
        if not isinstance(entry, dict) or not isinstance(entry.get("members"), list) or not entry["members"]:
            raise Invalid("Each group needs a member list.")
        members = [identifier(value) for value in entry["members"]]
        representative = identifier(entry.get("representative", members[0]))
        if representative not in members:
            raise Invalid("The representative must belong to its group.")
        for photo_id in members:
            if photo_id in seen:
                raise Invalid("A photograph appears in more than one group.")
            seen.add(photo_id)
        plan.append((members, representative))
    records = {photo["id"]: photo for photo in desk["photos"]}
    missing = seen - set(records)
    if missing:
        raise Invalid("A photograph in this plan no longer exists on the desk.")
    first = records[plan[0][0][0]]
    box = rectangle(data.get("box"), first["width"], first["height"], "Watch region")
    burst_id = key()
    for members, representative in plan:
        if len(members) == 1:
            continue
        records[representative]["used"] = True
        records[representative]["represented_by"] = None
        for photo_id in members:
            if photo_id == representative:
                continue
            photo = records[photo_id]
            photo["used"] = False
            photo["approved"] = False
            photo["represented_by"] = representative
    desk.setdefault("burst_history", []).insert(0, {
        "id": burst_id, "created_at": now(), "mode": mode,
        "threshold": threshold, "box": box,
        "groups": [{"representative": representative, "members": members} for members, representative in plan],
    })
    del desk["burst_history"][MAX_BURST_HISTORY:]
    return burst_id
