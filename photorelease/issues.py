from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from image_lab.validation import Invalid

from . import images, model, packaging
from .store import sha256


MANIFEST = model.MANIFEST_NAME
SCHEMA = model.RELEASE_SCHEMA
MAX_ARCHIVE = model.MAX_ARCHIVE


def used_photos(desk):
    return [photo for photo in desk["photos"] if photo["used"]]


def archive_bytes(files):
    from zipfile import ZIP_STORED

    output = BytesIO()
    with ZipFile(output, "w", allowZip64=False) as archive:
        # Stored (not deflated) members keep planned and issued ZIP sizes identical.
        for name, data in files.items():
            archive.writestr(name, data, compress_type=ZIP_STORED)
    return output.getvalue()


def _default_qualities(selection):
    return [
        model.JPEG_QUALITY_MAX if photo["style"]["format"] == "jpg" else None
        for photo in selection
    ]


def build_issue(library, desk, title, plan=None):
    if len(desk["issues"]) >= model.MAX_ISSUES:
        raise Invalid(f"A desk can retain up to {model.MAX_ISSUES} issues.")
    selection = used_photos(desk)
    if not selection:
        raise Invalid("Include at least one photo to create an issue.")
    if any(not photo["approved"] for photo in selection):
        raise Invalid("Approve every included photo in the current draft before issuing it.")

    if plan is None:
        qualities = _default_qualities(selection)
        cap = MAX_ARCHIVE
    else:
        cap = packaging.parse_cap(plan.get("cap_bytes"))
        floor = packaging.parse_floor(plan.get("min_quality"))
        qualities = _plan_qualities(selection, plan, floor)

    planner = packaging.PackagePlanner(library.blobs, selection)
    assembly = planner.assemble(qualities, title)
    if len(assembly["zip_bytes"]) > cap:
        raise Invalid("The chosen package no longer fits the cap. Re-open the package plans and try again.")
    if len(assembly["zip_bytes"]) > MAX_ARCHIVE - 128 * 1024:
        raise Invalid("The issue is too large to verify. Use a smaller output size or fewer large photos.")

    issue_id = model.key()
    created = model.now()
    assembly = planner.assemble(qualities, title, issue_id=issue_id, created_at=created)
    manifest = assembly["manifest"]
    archive_members = assembly["archive_members"]
    zip_payload = archive_bytes(archive_members)

    private_photos = []
    for row, photo in zip(assembly["rows"], selection):
        private_photos.append({
            "path": row["path"], "width": row["width"], "height": row["height"],
            "caption": row["caption"], "sha256": row["sha256"], "bytes": row["bytes"],
            "jpeg_quality": row["jpeg_quality"],
            "source_id": photo["id"], "file": library.blobs.put(archive_members[row["path"]]),
            "crop": images.extent(photo), "name": photo["name"],
        })
    document = {
        "id": issue_id, "title": title, "created_at": created,
        "revision": desk["revision"], "photos": private_photos,
        "archive": library.blobs.put(zip_payload), "manifest": manifest,
    }
    library.save_issue(document)
    summary = {field: document[field] for field in ("id", "title", "created_at", "revision")}
    summary["photo_count"] = len(private_photos)
    desk["issues"].append(summary)
    return document


def _plan_qualities(selection, plan, floor):
    kind = model.choice(plan.get("kind"), ("balanced", "lead"), "package plan")
    lead_id = plan.get("lead_photo_id")
    if lead_id is not None:
        model.select(selection, lead_id, "Lead photo")
    offered = plan.get("qualities")
    if not isinstance(offered, list) or len(offered) != len(selection):
        raise Invalid("The chosen package plan does not match the current selection.")
    qualities = []
    for entry, photo in zip(offered, selection):
        if photo["style"]["format"] == "png":
            if entry is not None:
                raise Invalid("The chosen package plan does not match the current photo formats.")
            qualities.append(None)
        else:
            quality = model.integer(entry, "Planned JPEG quality", floor, model.JPEG_QUALITY_MAX)
            qualities.append(quality)
    return qualities


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
