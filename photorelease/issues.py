from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from PIL import Image

from image_lab.validation import Invalid

from . import images, model
from .store import json_bytes, sha256


MANIFEST = "release.json"
SCHEMA = "photorelease-public-v1"
MAX_ARCHIVE = 96 * 1024 * 1024


def used_photos(desk):
    return [photo for photo in desk["photos"] if photo["used"]]


def archive_bytes(files):
    output = BytesIO()
    with ZipFile(output, "w", allowZip64=False) as archive:
        for name, data in files.items():
            compression = ZIP_DEFLATED if name == MANIFEST else ZIP_STORED
            archive.writestr(name, data, compress_type=compression)
    return output.getvalue()


def build_issue(library, desk, title):
    if len(desk["issues"]) >= model.MAX_ISSUES:
        raise Invalid(f"A desk can retain up to {model.MAX_ISSUES} issues.")
    selection = used_photos(desk)
    if not selection:
        raise Invalid("Include at least one photo to create an issue.")
    if any(not photo["approved"] for photo in selection):
        raise Invalid("Approve every included photo in the current draft before issuing it.")
    issue_id = model.key()
    created = model.now()
    archive_members = {}
    public_photos, private_photos, sheet_items = [], [], []
    total_bytes = 0
    for index, photo in enumerate(selection, start=1):
        style = photo["style"]
        rendered = images.create_rendition(library.blobs, photo)
        payload = images.encode(rendered, style["format"])
        total_bytes += len(payload)
        _budget(total_bytes)
        path = f"photos/{index:02d}.{style['format']}"
        record = {
            "path": path, "width": rendered.width, "height": rendered.height,
            "caption": style["caption"], "sha256": sha256(payload), "bytes": len(payload),
        }
        public_photos.append(record)
        private_photos.append({
            **record, "source_id": photo["id"], "file": library.blobs.put(payload),
            "crop": images.extent(photo), "name": photo["name"],
        })
        archive_members[path] = payload
        thumbnail = images.open_bytes(payload)
        thumbnail.thumbnail((304, 180), Image.Resampling.LANCZOS)
        sheet_items.append((thumbnail, style["caption"] or f"Photo {index:02d}"))
    sheets = []
    for number, items in enumerate(images.sheet_pages(sheet_items), start=1):
        raster = images.sheet_page(items, title, number)
        path = f"contact/{number:02d}.png"
        payload = images.encode(raster)
        total_bytes += len(payload)
        _budget(total_bytes)
        archive_members[path] = payload
        sheets.append({"path": path, "sha256": sha256(payload), "bytes": len(payload)})
    manifest = {
        "schema": SCHEMA, "issue": issue_id, "title": title, "created_at": created,
        "photos": public_photos, "contact_sheets": sheets,
    }
    archive_members[MANIFEST] = json_bytes(manifest)
    document = {
        "id": issue_id, "title": title, "created_at": created,
        "revision": desk["revision"], "photos": private_photos,
        "archive": library.blobs.put(archive_bytes(archive_members)), "manifest": manifest,
    }
    library.save_issue(document)
    summary = {field: document[field] for field in ("id", "title", "created_at", "revision")}
    summary["photo_count"] = len(private_photos)
    desk["issues"].append(summary)
    return document


def _budget(total):
    if total > MAX_ARCHIVE - 128 * 1024:
        raise Invalid("The issue is too large to verify. Use a smaller output size or fewer large photos.")


def issue_photo(document, source_id):
    model.identifier(source_id)
    for photo in document["photos"]:
        if photo["source_id"] == source_id:
            return photo
    raise Invalid("This photo was not included in the selected issue.")


def _archive_paths(archive):
    files = archive.infolist()
    if len(files) > model.MAX_PHOTOS + 6 or sum(item.file_size for item in files) > MAX_ARCHIVE:
        raise Invalid("The release ZIP exceeds the inspection limits.")
    names = set()
    for item in files:
        path = PurePosixPath(item.filename)
        if item.is_dir() or path.is_absolute() or ".." in path.parts or "\\" in item.filename:
            raise Invalid("An unexpected path was found in the release ZIP.")
        name = path.as_posix()
        if name in names or name != item.filename:
            raise Invalid("The release ZIP contains a duplicate or ambiguous path.")
        names.add(name)
    return names


def _manifest(archive, names):
    import json

    if MANIFEST not in names or archive.getinfo(MANIFEST).file_size > 64 * 1024:
        raise Invalid("The release manifest is missing or too large.")
    manifest = json.loads(archive.read(MANIFEST))
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise Invalid("This ZIP is not a PhotoRelease issue.")
    for section in ("photos", "contact_sheets"):
        if not isinstance(manifest.get(section), list) or not manifest[section]:
            raise Invalid("The release manifest is incomplete.")
    return manifest


def inspect_archive(payload):
    if not payload or len(payload) > MAX_ARCHIVE:
        raise Invalid("Choose a release ZIP no larger than 96 MB.")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            names = _archive_paths(archive)
            manifest = _manifest(archive, names)
            checks = []
            expected = {MANIFEST}
            for entry in manifest["photos"] + manifest["contact_sheets"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    raise Invalid("The release has an invalid file entry.")
                name = entry["path"]
                if name in expected:
                    raise Invalid("The release lists the same file more than once.")
                expected.add(name)
                if name in names:
                    raw = archive.read(name)
                    state = "matches" if len(raw) == entry.get("bytes") and sha256(raw) == entry.get("sha256") else "changed"
                else:
                    state = "missing"
                checks.append({"path": name, "state": state})
            checks.extend({"path": name, "state": "extra"} for name in sorted(names - expected))
    except (BadZipFile, UnicodeError, ValueError, NotImplementedError, RuntimeError) as error:
        if isinstance(error, Invalid):
            raise
        raise Invalid("The selected release ZIP or manifest cannot be read.") from error
    return {
        "title": str(manifest.get("title", ""))[:120],
        "valid": all(entry["state"] == "matches" for entry in checks),
        "files": checks,
    }
