import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photorelease.__main__ import application
from photorelease import images, model, packaging
from photorelease.store import Library


def make_client(tmp):
    app = application(tmp)
    app.testing = True
    return app.test_client(), app.extensions["photo_release"]


def jpg_upload(seed, size=(1400, 950)):
    from PIL import Image
    import numpy as np

    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(90, 90, 3), dtype=np.uint8)
    img = Image.fromarray(base).resize(size, Image.Resampling.NEAREST)
    arr = np.asarray(img).astype(np.int16) + rng.normal(0, 6, size=(*size[::-1], 1))
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf


def tiff_upload(seed, size=(1000, 700)):
    from PIL import Image
    import numpy as np

    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(*size[::-1], 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "TIFF")
    buf.seek(0)
    return buf


def png_upload(seed, size=(800, 560)):
    from PIL import Image
    import numpy as np

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size[1], 0:size[0]]
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[..., 0] = (xx * 255 // size[0])
    arr[..., 1] = (yy * 255 // size[1])
    arr[..., 2] = ((xx + yy) * 255 // (size[0] + size[1]))
    arr = np.clip(arr.astype(np.int16) + rng.normal(0, 1.2, size=(*size[::-1], 1)), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def add_photo(client, desk_id, revision, buf, filename):
    response = client.post(
        f"/release/desks/{desk_id}/photos",
        data={"file": (buf, filename), "revision": str(revision)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def set_style_and_approve(client, desk, photo, style):
    response = client.patch(f"/release/desks/{desk['id']}/photos/{photo['id']}",
                            json={"revision": desk["revision"], "style": style})
    assert response.status_code == 200, response.get_json()
    desk = response.get_json()
    photo = next(item for item in desk["photos"] if item["id"] == photo["id"])
    response = client.patch(f"/release/desks/{desk['id']}/photos/{photo['id']}",
                            json={"revision": desk["revision"], "approved": True})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_packaging_plans_and_issue():
    with tempfile.TemporaryDirectory() as tmp:
        client, library = make_client(tmp)
        response = client.post("/release/desks", json={"title": "Test desk"})
        desk = response.get_json()
        desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(1), "one.jpg")
        desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(2), "two.jpg")
        desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(3), "three.jpg")
        desk = add_photo(client, desk["id"], desk["revision"], png_upload(4), "four.png")

        photos = desk["photos"]
        desk = set_style_and_approve(client, desk, photos[0], {"format": "jpg", "edge": "screen"})
        desk = set_style_and_approve(client, desk, photos[1], {"format": "jpg", "edge": "screen"})
        desk = set_style_and_approve(client, desk, photos[2], {"format": "jpg", "edge": "screen"})
        desk = set_style_and_approve(client, desk, photos[3], {"format": "png", "edge": "screen"})
        photos = desk["photos"]
        lead_id = photos[0]["id"]

        cap = 5 * 1024 * 1024
        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "Issue 42", "cap_bytes": cap, "min_quality": 55, "lead_photo_id": lead_id,
        })
        assert response.status_code == 200, response.get_json()
        plans = response.get_json()
        assert plans["feasible"] is True

        balanced, lead = plans["balanced"], plans["lead"]
        # Balanced plan uses one common JPEG quality.
        balanced_qualities = [row["jpeg_quality"] for row in balanced["photos"] if row["jpeg_quality"] is not None]
        assert len(set(balanced_qualities)) == 1
        # Both plans fit the cap and respect the floor.
        assert balanced["total_bytes"] <= cap
        assert lead["total_bytes"] <= cap
        assert min(balanced_qualities) >= 55
        # Lead plan gives the lead the highest quality of the two plans.
        lead_quality_balanced = next(row for row in balanced["photos"] if row["source_id"] == lead_id)["jpeg_quality"]
        lead_quality_lead = next(row for row in lead["photos"] if row["source_id"] == lead_id)["jpeg_quality"]
        assert lead_quality_lead >= lead_quality_balanced
        # PNG photo is byte-identical in both plans.
        png_balanced = next(row for row in balanced["photos"] if row["format"] == "png")
        png_lead = next(row for row in lead["photos"] if row["format"] == "png")
        assert png_balanced["bytes"] == png_lead["bytes"]
        assert png_balanced["jpeg_quality"] is None
        # Dimensions unchanged.
        for row in balanced["photos"]:
            source = next(photo for photo in photos if photo["id"] == row["source_id"])
            review = client.get(f"/release/desks/{desk['id']}/photos/{source['id']}/review").get_json()
            assert (row["width"], row["height"]) == tuple(review["size"])

        # Issue the balanced plan; the issued ZIP must be byte-for-byte the planned size.
        response = client.post(f"/release/desks/{desk['id']}/issues", json={
            "revision": desk["revision"], "title": "Issue 42",
            "plan": {"kind": "balanced", "cap_bytes": cap, "min_quality": 55,
                     "lead_photo_id": lead_id, "qualities": balanced["qualities"]},
        })
        assert response.status_code == 201, response.get_json()
        desk = response.get_json()
        issue_id = desk["issues"][0]["id"]

        issue_doc = json.loads((Path(tmp) / "release" / "issues" / f"{issue_id}.json").read_text())
        archive_path = Path(tmp) / "release" / "blobs" / issue_doc["archive"][:2] / issue_doc["archive"]
        issued_zip = archive_path.read_bytes()
        assert len(issued_zip) == balanced["total_bytes"], (len(issued_zip), balanced["total_bytes"])

        with zipfile.ZipFile(io.BytesIO(issued_zip)) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("release.json"))
            for entry in manifest["photos"] + manifest["contact_sheets"]:
                assert entry["path"] in names
        # Stored photo qualities match the plan.
        stored_qualities = [row["jpeg_quality"] for row in issue_doc["photos"] if row["jpeg_quality"] is not None]
        assert stored_qualities == balanced_qualities

        # Download endpoint serves the same bytes; verify endpoint accepts the ZIP.
        download = client.get(f"/release/desks/{desk['id']}/issues/{issue_id}/download")
        assert download.data == issued_zip
        inspect = client.post("/release/inspect", data={"file": (io.BytesIO(issued_zip), "x.zip")},
                              content_type="multipart/form-data").get_json()
        assert inspect["valid"] is True, inspect

        # A second (lead) issue can be created; the first archive stays untouched.
        response = client.post(f"/release/desks/{desk['id']}/issues", json={
            "revision": desk["revision"], "title": "Issue 43",
            "plan": {"kind": "lead", "cap_bytes": cap, "min_quality": 55,
                     "lead_photo_id": lead_id, "qualities": lead["qualities"]},
        })
        assert response.status_code == 201, response.get_json()
        desk = response.get_json()
        assert len(desk["issues"]) == 2
        assert archive_path.read_bytes() == issued_zip


def test_infeasible_cap_reports_fixed_costs():
    with tempfile.TemporaryDirectory() as tmp:
        client, library = make_client(tmp)
        desk = client.post("/release/desks", json={"title": "Tight desk"}).get_json()
        desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(10), "big.jpg")
        desk = add_photo(client, desk["id"], desk["revision"], png_upload(11), "fixed.png")
        photos = desk["photos"]
        desk = set_style_and_approve(client, desk, photos[0], {"format": "jpg"})
        desk = set_style_and_approve(client, desk, photos[1], {"format": "png"})

        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "Tight", "cap_bytes": 512 * 1024, "min_quality": 40,
        })
        assert response.status_code == 200
        plans = response.get_json()
        assert plans["feasible"] is False
        assert "balanced" not in plans
        fixed = plans["fixed"]
        assert fixed["floor_total_bytes"] > plans["cap_bytes"]
        # Fixed subtotal contains the PNG, sheets, manifest and overhead.
        assert fixed["fixed_bytes"] > 0
        assert fixed["jpeg_floor_bytes"] > 0
        png_row = next(row for row in fixed["rows"] if row["fixed"])
        assert png_row["format"] == "png"
        # No issue was created.
        assert desk["issues"] == []
        reopened = client.get(f"/release/desks/{desk['id']}").get_json()
        assert reopened["issues"] == []

        # Relaxing the cap makes the same desk feasible without touching settings.
        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "Tight", "cap_bytes": 90 * 1024 * 1024, "min_quality": 40,
        })
        assert response.get_json()["feasible"] is True


def test_validation_and_legacy_issue():
    with tempfile.TemporaryDirectory() as tmp:
        client, library = make_client(tmp)
        desk = client.post("/release/desks", json={"title": "Validation desk"}).get_json()
        desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(20), "a.jpg")
        # Planning before approval is rejected.
        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "X", "cap_bytes": 5 * 1024 * 1024, "min_quality": 50,
        })
        assert response.status_code == 400

        photo = desk["photos"][0]
        desk = set_style_and_approve(client, desk, photo, {"format": "jpg"})
        # Out-of-range cap and quality.
        assert client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "X", "cap_bytes": 1024, "min_quality": 50}).status_code == 400
        assert client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "X", "cap_bytes": 5 * 1024 * 1024, "min_quality": 10}).status_code == 400
        # Unknown lead photo.
        assert client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "X", "cap_bytes": 5 * 1024 * 1024, "min_quality": 50,
            "lead_photo_id": "a" * 32}).status_code == 400

        # Legacy issue creation without a plan still works at the default quality 92.
        response = client.post(f"/release/desks/{desk['id']}/issues",
                               json={"revision": desk["revision"], "title": "Legacy"})
        assert response.status_code == 201, response.get_json()
        desk = response.get_json()
        issue_id = desk["issues"][0]["id"]
        issue_doc = json.loads((Path(tmp) / "release" / "issues" / f"{issue_id}.json").read_text())
        assert issue_doc["photos"][0]["jpeg_quality"] == model.JPEG_QUALITY_MAX

        # A tampered plan (quality below the declared floor) is rejected.
        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "X", "cap_bytes": 5 * 1024 * 1024, "min_quality": 60})
        plans = response.get_json()
        bad = client.post(f"/release/desks/{desk['id']}/issues", json={
            "revision": desk["revision"], "title": "Bad",
            "plan": {"kind": "balanced", "cap_bytes": 5 * 1024 * 1024, "min_quality": 60,
                     "qualities": [40]}})
        assert bad.status_code == 400


def test_planner_monotonic_and_exact_fit():
    with tempfile.TemporaryDirectory() as tmp:
        client, library = make_client(tmp)
        desk = client.post("/release/desks", json={"title": "Planner desk"}).get_json()
        for seed in range(4):
            desk = add_photo(client, desk["id"], desk["revision"], jpg_upload(30 + seed), f"p{seed}.jpg")
        for photo in desk["photos"]:
            desk = set_style_and_approve(client, desk, photo, {"format": "jpg"})

        response = client.post(f"/release/desks/{desk['id']}/package-plans", json={
            "title": "P", "cap_bytes": 30 * 1024 * 1024, "min_quality": 40})
        plans = response.get_json()
        # Generous cap means no quality loss at all.
        assert all(q == model.JPEG_QUALITY_MAX for q in plans["balanced"]["qualities"])

        # Direct planner check: sizes shrink as quality drops (PIL monotonicity assumption).
        full = client.get(f"/release/desks/{desk['id']}").get_json()
        library = app_extension(client)
        selection = [photo for photo in full["photos"] if photo["used"]]
        planner = packaging.PackagePlanner(library.blobs, selection)
        previous = None
        for quality in range(model.JPEG_QUALITY_MAX, model.JPEG_QUALITY_FLOOR - 1, -5):
            size = len(planner.assemble([quality] * len(selection), "P")["zip_bytes"])
            if previous is not None:
                assert size <= previous
            previous = size


def app_extension(client):
    return client.application.extensions["photo_release"]


if __name__ == "__main__":
    test_packaging_plans_and_issue()
    test_infeasible_cap_reports_fixed_costs()
    test_validation_and_legacy_issue()
    test_planner_monotonic_and_exact_fit()
    print("all packaging tests passed")
