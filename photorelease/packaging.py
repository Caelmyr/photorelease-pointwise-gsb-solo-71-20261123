from io import BytesIO
from zipfile import ZIP_STORED, ZipFile

from PIL import Image

from image_lab.validation import Invalid

from . import images, model
from .store import json_bytes, sha256


PLACEHOLDER_ISSUE_ID = "0" * 32
PLACEHOLDER_CREATED = "1970-01-01T00:00:00+00:00"


class PackagePlanner:
    """Build exact release ZIP bytes and search quality assignments for a desk.

    Dimensions, crops, marks and file formats never change here. Only JPEG
    quality is adjusted; PNG photos are fixed exactly as the draft encodes them.
    """

    def __init__(self, blobs, photos):
        self.blobs = blobs
        self.photos = photos
        self._renditions = [images.create_rendition(blobs, photo) for photo in photos]
        self._jpeg_payloads = {}
        self._png_payloads = {}
        self._members_cache = {}

    # ---- per-photo encodings -------------------------------------------------

    def _photo_payload(self, index, quality):
        photo = self.photos[index]
        if photo["style"]["format"] == "png":
            if index not in self._png_payloads:
                self._png_payloads[index] = images.encode(self._renditions[index], "png")
            return self._png_payloads[index]
        cache = self._jpeg_payloads.setdefault(index, {})
        if quality not in cache:
            cache[quality] = images.encode(self._renditions[index], "jpg", quality)
        return cache[quality]

    def _sheet_items(self, payloads):
        items = []
        for index, (photo, payload) in enumerate(zip(self.photos, payloads), start=1):
            thumbnail = images.open_bytes(payload)
            thumbnail.thumbnail((304, 180), Image.Resampling.LANCZOS)
            items.append((thumbnail, photo["style"]["caption"] or f"Photo {index:02d}"))
        return items

    def _members(self, qualities, title):
        """Cached heavy work: photo and contact-sheet encodings for a quality tuple."""
        key = tuple(qualities)
        if key in self._members_cache:
            return self._members_cache[key]
        archive_members = {}
        rows = []
        sheet_payloads = []
        for index, photo in enumerate(self.photos):
            style = photo["style"]
            quality = qualities[index]
            payload = self._photo_payload(index, quality)
            path = f"photos/{index + 1:02d}.{style['format']}"
            rendered = self._renditions[index]
            row = {
                "source_id": photo["id"], "name": photo["name"], "path": path,
                "format": style["format"], "width": rendered.width, "height": rendered.height,
                "caption": style["caption"], "bytes": len(payload), "sha256": sha256(payload),
                "jpeg_quality": quality if style["format"] == "jpg" else None,
            }
            rows.append(row)
            archive_members[path] = payload
            sheet_payloads.append(payload)

        sheets = []
        items = self._sheet_items(sheet_payloads)
        for number, batch in enumerate(images.sheet_pages(items), start=1):
            raster = images.sheet_page(batch, title, number)
            path = f"contact/{number:02d}.png"
            payload = images.encode(raster)
            sheets.append({"path": path, "sha256": sha256(payload), "bytes": len(payload)})
            archive_members[path] = payload

        result = {"rows": rows, "sheets": sheets, "archive_members": archive_members}
        self._members_cache[key] = result
        return result

    # ---- exact archive assembly ---------------------------------------------

    def assemble(self, qualities, title, issue_id=None, created_at=None):
        """Return the exact ZIP bytes and a structured breakdown.

        Planning calls use fixed-length placeholders for issue id and timestamp,
        so the reported ZIP size is byte-identical to the issued archive.
        """
        parts = self._members(qualities, title)
        manifest = {
            "schema": model.RELEASE_SCHEMA, "issue": issue_id or PLACEHOLDER_ISSUE_ID,
            "created_at": created_at or PLACEHOLDER_CREATED, "title": title,
            "photos": [
                {key: row[key] for key in ("path", "width", "height", "caption", "sha256", "bytes", "jpeg_quality")}
                for row in parts["rows"]
            ],
            "contact_sheets": parts["sheets"],
        }
        manifest_bytes = json_bytes(manifest)
        archive_members = dict(parts["archive_members"])
        archive_members[model.MANIFEST_NAME] = manifest_bytes

        output = BytesIO()
        with ZipFile(output, "w", allowZip64=False) as archive:
            # Every member is stored uncompressed so the planned ZIP size stays
            # byte-identical regardless of manifest content (ids and timestamps).
            for name, data in archive_members.items():
                archive.writestr(name, data, compress_type=ZIP_STORED)
        zip_bytes = output.getvalue()
        member_bytes = sum(len(data) for data in archive_members.values())

        return {
            "zip_bytes": zip_bytes,
            "overhead_bytes": len(zip_bytes) - member_bytes,
            "manifest_bytes": len(manifest_bytes),
            "rows": parts["rows"],
            "sheets": parts["sheets"],
            "archive_members": archive_members,
            "manifest": manifest,
            "qualities": list(qualities),
        }

    def fits(self, qualities, title, cap):
        return len(self.assemble(qualities, title)["zip_bytes"]) <= cap

    # ---- plan search ---------------------------------------------------------

    def jpeg_indexes(self):
        return [index for index, photo in enumerate(self.photos) if photo["style"]["format"] == "jpg"]

    def _initial_qualities(self):
        return [
            model.JPEG_QUALITY_MAX if photo["style"]["format"] == "jpg" else None
            for photo in self.photos
        ]

    def balanced_plan(self, cap, floor, title):
        """Highest common JPEG quality that fits (spreads the loss evenly)."""
        jpegs = self.jpeg_indexes()
        qualities = self._initial_qualities()
        low, high = floor, model.JPEG_QUALITY_MAX
        best = None
        while low <= high:
            middle = (low + high) // 2
            for index in jpegs:
                qualities[index] = middle
            if self.fits(qualities, title, cap):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            return None
        for index in jpegs:
            qualities[index] = best
        return self.assemble(qualities, title)

    def lead_plan(self, cap, floor, title, lead_id):
        """Protect one long-read lead photo at the highest quality possible."""
        jpegs = self.jpeg_indexes()
        lead = next((index for index, photo in enumerate(self.photos) if photo["id"] == lead_id), None)
        qualities = self._initial_qualities()
        if lead is None or self.photos[lead]["style"]["format"] != "jpg":
            return self.balanced_plan(cap, floor, title)

        # Phase 1: keep the lead at maximum quality, find the best common level for every other JPEG.
        others = [index for index in jpegs if index != lead]
        qualities[lead] = model.JPEG_QUALITY_MAX
        level = self._search_common(qualities, others, cap, floor, title)
        if level is not None:
            for index in others:
                qualities[index] = level
            return self.assemble(qualities, title)

        # Phase 2: other JPEGs already at the floor; lower the lead only as far as needed.
        for index in others:
            qualities[index] = floor
        low, high = floor, model.JPEG_QUALITY_MAX
        best = None
        while low <= high:
            middle = (low + high) // 2
            qualities[lead] = middle
            if self.fits(qualities, title, cap):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            return None
        qualities[lead] = best
        return self.assemble(qualities, title)

    def _search_common(self, qualities, indexes, cap, floor, title):
        low, high = floor, model.JPEG_QUALITY_MAX
        best = None
        while low <= high:
            middle = (low + high) // 2
            for index in indexes:
                qualities[index] = middle
            if self.fits(qualities, title, cap):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    # ---- reporting -----------------------------------------------------------

    def floor_assembly(self, floor, title):
        qualities = [
            floor if photo["style"]["format"] == "jpg" else None
            for photo in self.photos
        ]
        return self.assemble(qualities, title)

    def fixed_cost(self, floor, title):
        """Cost of everything that cannot be changed by JPEG quality."""
        assembly = self.floor_assembly(floor, title)
        photo_rows = [
            {**row, "fixed": row["format"] == "png"}
            for row in assembly["rows"]
        ]
        fixed_photos = sum(row["bytes"] for row in photo_rows if row["fixed"])
        jpeg_floor = sum(row["bytes"] for row in photo_rows if not row["fixed"])
        sheets = sum(row["bytes"] for row in assembly["sheets"])
        return {
            "rows": photo_rows,
            "sheet_bytes": sheets,
            "manifest_bytes": assembly["manifest_bytes"],
            "overhead_bytes": assembly["overhead_bytes"],
            "fixed_bytes": fixed_photos + sheets + assembly["manifest_bytes"] + assembly["overhead_bytes"],
            "jpeg_floor_bytes": jpeg_floor,
            "floor_total_bytes": len(assembly["zip_bytes"]),
            "assembly": assembly,
        }


def parse_cap(value):
    return model.integer(value, "Total package cap", model.PACKAGE_CAP_MIN, model.MAX_ARCHIVE)


def parse_floor(value):
    return model.integer(
        value, "Minimum JPEG quality", model.JPEG_QUALITY_FLOOR, model.JPEG_QUALITY_MAX
    )


def plan_payload(planner, assembly, kind):
    return {
        "kind": kind,
        "total_bytes": len(assembly["zip_bytes"]),
        "overhead_bytes": assembly["overhead_bytes"],
        "manifest_bytes": assembly["manifest_bytes"],
        "qualities": assembly["qualities"],
        "photos": [
            {
                "source_id": row["source_id"], "name": row["name"], "path": row["path"],
                "format": row["format"], "width": row["width"], "height": row["height"],
                "caption": row["caption"], "bytes": row["bytes"],
                "jpeg_quality": row["jpeg_quality"],
            }
            for row in assembly["rows"]
        ],
        "contact_sheets": assembly["sheets"],
    }


def build_plans(library, desk, cap, floor, lead_id, title):
    selection = [photo for photo in desk["photos"] if photo["used"]]
    if not selection:
        raise Invalid("Include at least one photo before comparing package plans.")
    if any(not photo["approved"] for photo in selection):
        raise Invalid("Approve every included photo in the current draft before planning a package.")
    if lead_id is not None:
        model.select(selection, lead_id, "Lead photo")

    planner = PackagePlanner(library.blobs, selection)
    fixed = planner.fixed_cost(floor, title)
    floor_assembly = fixed["assembly"]
    feasible = len(floor_assembly["zip_bytes"]) <= cap

    response = {
        "cap_bytes": cap,
        "min_quality": floor,
        "feasible": feasible,
        "title": title,
        "fixed": {key: value for key, value in fixed.items() if key != "assembly"},
        "floor_plan": plan_payload(planner, floor_assembly, "floor"),
    }
    if feasible:
        response["balanced"] = plan_payload(planner, planner.balanced_plan(cap, floor, title), "balanced")
        response["lead"] = plan_payload(
            planner, planner.lead_plan(cap, floor, title, lead_id or selection[0]["id"]), "lead"
        )
        response["lead_photo_id"] = lead_id or selection[0]["id"]
    return response
