from io import BytesIO

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from image_lab.validation import Invalid

from . import demo, images, issues, model
from .store import Library


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise Invalid("Send a JSON object with this edit.")
    return value


def image_response(image):
    return Response(images.encode(image), mimetype="image/png", headers={"Cache-Control": "no-store"})


def upload(limit):
    entry = request.files.get("file")
    if entry is None:
        raise Invalid("Choose a file first.")
    return entry.read(limit + 1), entry.filename


def checked_flag(value):
    if not isinstance(value, bool):
        raise Invalid("Choose either yes or no.")
    return value


def install(app, directory):
    library = Library(directory)
    release = Blueprint("release", __name__, url_prefix="/release")
    app.extensions["photo_release"] = library
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    @app.get("/")
    def home():
        return render_template("release.html")

    @release.get("/health")
    def health():
        return jsonify(status="ok", service="PhotoRelease")

    @release.get("/desks")
    def desks():
        return jsonify(library.list())

    @release.post("/desks")
    def create_desk():
        desk = model.new_desk(body().get("title", "Untitled desk"))
        return jsonify(library.add(desk)), 201

    @release.post("/demo")
    def demo_desk():
        return jsonify(demo.create(library)), 201

    @release.get("/desks/<key>")
    def get_desk(key):
        return jsonify(library.open(key))

    @release.post("/desks/<key>/photos")
    def add_photo(key):
        raw, filename = upload(images.MAX_INPUT_BYTES)
        try:
            revision = int(request.form.get("revision", ""))
        except ValueError as error:
            raise Invalid("The current desk revision is required.") from error

        def change(desk):
            _ensure_photo_slot(desk)
            desk["photos"].append(images.from_upload(library.blobs, raw, filename))

        return jsonify(library.mutate(key, revision, change)), 201

    @release.get("/preparation")
    def preparation():
        sources = app.extensions["assets"].list("image")
        projects = app.extensions["store"].list()
        results = []
        for project in projects:
            for item in app.extensions["results"].list(project["id"]):
                item["project_id"] = project["id"]
                results.append(item)
        return jsonify(assets=sources, results=results)

    @release.post("/desks/<key>/prepared-photo")
    def add_prepared_photo(key):
        data = body()

        def change(desk):
            _ensure_photo_slot(desk)
            kind = model.choice(data.get("kind"), ("asset", "result"), "prepared photo source")
            if kind == "asset":
                identifier = data.get("asset_id")
                assets = app.extensions["assets"]
                meta = assets.metadata(identifier)
                if meta["kind"] != "image":
                    raise Invalid("Only photo assets can be brought into a release desk.")
                pixels = assets.field(identifier)
                name = meta["name"]
                origin = {"asset": identifier}
            else:
                project = data.get("project_id")
                result = data.get("result_id")
                fields, meta = app.extensions["results"].fields(project, result, require_current=False)
                pixels = fields["image"]
                name = meta["name"]
                origin = {"project": project, "result": result}
            desk["photos"].append(images.from_preparation(library.blobs, pixels, origin, name, kind))

        return jsonify(library.mutate(key, data.get("revision"), change)), 201

    @release.get("/desks/<key>/photos/<photo_id>/image/<view>")
    def photo_image(key, photo_id, view):
        desk = library.open(key)
        photo = model.select(desk["photos"], photo_id, "Photo")
        if view == "working":
            result = images.working_image(library.blobs, photo, 1400)
        elif view == "thumb":
            result = images.working_image(library.blobs, photo, 200)
        elif view == "draft":
            published = images.create_rendition(library.blobs, photo)
            payload = images.encode(published, photo["style"]["format"])
            return Response(payload, mimetype=model.FORMATS[photo["style"]["format"]], headers={"Cache-Control": "no-store"})
        else:
            raise Invalid("Choose an available photo view.")
        return image_response(result)

    @release.get("/desks/<key>/photos/<photo_id>/review")
    def photo_review(key, photo_id):
        desk = library.open(key)
        return jsonify(images.crop_review(model.select(desk["photos"], photo_id, "Photo")))

    @release.patch("/desks/<key>/photos/<photo_id>")
    def edit_photo(key, photo_id):
        data = body()

        def change(desk):
            photo = model.select(desk["photos"], photo_id, "Photo")
            if "style" in data:
                if not isinstance(data["style"], dict):
                    raise Invalid("Photo output settings must be an object.")
                model.change_style(photo, data["style"])
            if "used" in data:
                photo["used"] = checked_flag(data["used"])
            if "approved" in data:
                photo["approved"] = checked_flag(data["approved"])
            if "move" in data:
                _move_photo(desk, photo, data["move"])

        return jsonify(library.mutate(key, data.get("revision"), change))

    @release.post("/desks/<key>/photos/<photo_id>/marks")
    def create_mark(key, photo_id):
        data = body()

        def change(desk):
            model.new_mark(model.select(desk["photos"], photo_id, "Photo"), data)

        return jsonify(library.mutate(key, data.get("revision"), change)), 201

    @release.patch("/desks/<key>/photos/<photo_id>/marks/<mark_id>")
    def edit_mark(key, photo_id, mark_id):
        data = body()

        def change(desk):
            photo = model.select(desk["photos"], photo_id, "Photo")
            model.update_mark(photo, model.select(photo["marks"], mark_id, "Mark"), data)

        return jsonify(library.mutate(key, data.get("revision"), change))

    @release.delete("/desks/<key>/photos/<photo_id>/marks/<mark_id>")
    def remove_mark(key, photo_id, mark_id):
        data = body()

        def change(desk):
            photo = model.select(desk["photos"], photo_id, "Photo")
            photo["marks"].remove(model.select(photo["marks"], mark_id, "Mark"))
            photo["approved"] = False

        return jsonify(library.mutate(key, data.get("revision"), change))

    @release.get("/desks/<key>/contact/<int:page>")
    def contact(key, page):
        desk = library.open(key)
        selection = issues.used_photos(desk)
        first = (page - 1) * images.SHEET_PAGE_LIMIT
        if page < 1 or first >= len(selection):
            raise Invalid("This contact sheet page is empty.")
        items = [
            (images.create_rendition(library.blobs, photo), photo["style"]["caption"] or f"Photo {index:02d}")
            for index, photo in enumerate(selection[first:first + images.SHEET_PAGE_LIMIT], start=first + 1)
        ]
        return image_response(images.sheet_page(items, "Working contact sheet", page))

    @release.post("/desks/<key>/issues")
    def create_issue(key):
        data = body()
        title = model.text(data.get("title", ""), "Public issue title", 75, True)

        def change(desk):
            issues.build_issue(library, desk, title)

        return jsonify(library.mutate(key, data.get("revision"), change)), 201

    @release.get("/desks/<key>/issues/<issue_id>")
    def get_issue(key, issue_id):
        return jsonify(library.issue(library.open(key), issue_id))

    @release.get("/desks/<key>/issues/<issue_id>/download")
    def download_issue(key, issue_id):
        document = library.issue(library.open(key), issue_id)
        payload = library.blobs.read(document["archive"])
        return send_file(BytesIO(payload), as_attachment=True, download_name=f"photo-issue-{issue_id[:8]}.zip", mimetype="application/zip")

    @release.get("/desks/<key>/issues/<issue_id>/photos/<photo_id>")
    def archive_image(key, issue_id, photo_id):
        document = library.issue(library.open(key), issue_id)
        photo = issues.issue_photo(document, photo_id)
        format_name = photo["path"].rsplit(".", maxsplit=1)[-1]
        return Response(library.blobs.read(photo["file"]), mimetype=model.FORMATS[format_name])

    @release.get("/desks/<key>/compare")
    def compare_issues(key):
        desk = library.open(key)
        photo = request.args.get("photo")
        a = issues.issue_photo(library.issue(desk, request.args.get("first")), photo)
        b = issues.issue_photo(library.issue(desk, request.args.get("second")), photo)
        first, second = (images.open_bytes(library.blobs.read(row["file"])) for row in (a, b))
        highlight, report = images.visible_difference(first, second)
        return image_response(highlight) if request.args.get("format") == "png" else jsonify(report)

    @release.post("/inspect")
    def inspect():
        raw, _ = upload(issues.MAX_ARCHIVE)
        return jsonify(issues.inspect_archive(raw))

    app.register_blueprint(release)


def _move_photo(desk, photo, direction):
    direction = model.choice(direction, ("earlier", "later"), "movement")
    photos = desk["photos"]
    original = photos.index(photo)
    adjacent = original + (-1 if direction == "earlier" else 1)
    if 0 <= adjacent < len(photos):
        photos[original], photos[adjacent] = photos[adjacent], photos[original]


def _ensure_photo_slot(desk):
    if len(desk["photos"]) >= model.MAX_PHOTOS:
        raise Invalid(f"A desk can hold up to {model.MAX_PHOTOS} photos.")
