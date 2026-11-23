"""Burst grouping: compare a small set of same-size desk photos inside a region."""

import cv2
import numpy as np
from PIL import Image, ImageDraw

from image_lab.validation import Invalid

from . import images, model


ANALYSIS_EDGE = 480
GRID = (4, 6)  # rows, columns of local difference cells
MAX_GROUP_PHOTOS = 12
MAX_SHIFT = 4
MODES = ("anchor", "pairwise")


def _scale(photo):
    return min(1.0, ANALYSIS_EDGE / max(photo["width"], photo["height"]))


def region_pixels(blobs, photo, box, scale):
    image = images.working_image(blobs, photo)
    x0 = max(0, min(photo["width"], int(round(box[0] * scale))))
    y0 = max(0, min(photo["height"], int(round(box[1] * scale))))
    x1 = max(x0 + 1, min(photo["width"], int(round(box[2] * scale))))
    y1 = max(y0 + 1, min(photo["height"], int(round(box[3] * scale))))
    return np.asarray(image, dtype=np.uint8)[y0:y1, x0:x1]


def _phase_shift(reference, candidate, margin):
    """Sub-pixel translation of candidate relative to reference, clamped to margin."""
    a = cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY).astype(np.float32)
    b = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY).astype(np.float32)
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (shift_x, shift_y), _ = cv2.phaseCorrelate(np.log1p(a * 20), np.log1p(b * 20), window)
    if not (np.isfinite(shift_x) and np.isfinite(shift_y)):
        return 0, 0
    return int(round(np.clip(shift_x, -margin, margin))), int(round(np.clip(shift_y, -margin, margin)))


def pair_metrics(reference, candidate):
    """Best integer-shift MAE between two same-size RGB regions, plus local grid."""
    if reference.shape != candidate.shape:
        raise Invalid("The selected photographs have different pixel dimensions.")
    height, width = reference.shape[:2]
    a = reference.astype(np.float32)
    b = candidate.astype(np.float32)
    margin = min(MAX_SHIFT, max(width, height) // 4)
    shift = _phase_shift(a, b, margin) if margin else (0, 0)
    shift_x, shift_y = shift
    aligned = np.empty_like(b)
    aligned[:] = a
    src_x0, src_x1 = max(0, shift_x), min(width, width + shift_x)
    src_y0, src_y1 = max(0, shift_y), min(height, height + shift_y)
    aligned[max(0, -shift_y):min(height, height - shift_y),
            max(0, -shift_x):min(width, width - shift_x)] = \
        b[src_y0:src_y1, src_x0:src_x1]
    delta = np.abs(a - aligned)
    mae = float(delta.mean())
    rows, columns = GRID
    cell_h, cell_w = max(1, height // rows), max(1, width // columns)
    cells = []
    for row in range(rows):
        for column in range(columns):
            y0, x0 = row * cell_h, column * cell_w
            y1 = height if row == rows - 1 else y0 + cell_h
            x1 = width if column == columns - 1 else x0 + cell_w
            block = delta[y0:y1, x0:x1]
            cells.append(round(float(block.mean()), 2))
    return {
        "similarity": round(max(0.0, 100.0 * (1.0 - mae / 255.0)), 2),
        "mae": round(mae, 2),
        "shift": [shift_x, shift_y],
        "cells": cells,
        "max_cell": int(np.argmax(cells)),
    }


def _pair_table(members, pixels):
    table = {}
    for left in range(len(members)):
        for right in range(left + 1, len(members)):
            table[(left, right)] = pair_metrics(pixels[left], pixels[right])
    return table


def lookup_pair(table, left, right):
    if left == right:
        return None
    return table[(min(left, right), max(left, right))]


def _build_groups(mode, members, table, threshold):
    if mode == "anchor":
        groups, used = [], set()
        for index, photo_id in enumerate(members):
            if index in used:
                continue
            group = [index]
            for other in range(index + 1, len(members)):
                if other in used:
                    continue
                if lookup_pair(table, index, other)["similarity"] >= threshold:
                    group.append(other)
            used.update(group)
            groups.append(group)
        return groups
    groups, used = [], set()
    for index in range(len(members)):
        if index in used:
            continue
        group = [index]
        for other in range(index + 1, len(members)):
            if other in used:
                continue
            # every existing member must already resemble the candidate
            if all(lookup_pair(table, member, other)["similarity"] >= threshold for member in group):
                group.append(other)
        used.update(group)
        groups.append(group)
    return groups


def _representative(mode, members, group, table):
    if mode == "anchor" or len(group) == 1:
        return group[0]
    scores = [
        sum(lookup_pair(table, candidate, other)["similarity"] for other in group if other != candidate)
        for candidate in group
    ]
    return group[max(range(len(group)), key=lambda item: (scores[item], -item))]


def analyze(library, desk, data):
    mode = model.choice(data.get("mode", "anchor"), MODES, "grouping mode")
    threshold = model.integer(data.get("threshold", 90), "Similarity threshold", 0, 100)
    ids = data.get("photo_ids")
    if not isinstance(ids, list) or not 2 <= len(ids) <= MAX_GROUP_PHOTOS:
        raise Invalid(f"Choose between 2 and {MAX_GROUP_PHOTOS} photographs for the burst set.")
    photos = [model.select(desk["photos"], photo_id, "Photo") for photo_id in ids]
    base = photos[0]
    if any(photo["width"] != base["width"] or photo["height"] != base["height"] for photo in photos[1:]):
        raise Invalid("Burst grouping needs photographs with identical dimensions.")
    box = model.rectangle(data.get("box"), base["width"], base["height"], "Watch region")
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        raise Invalid("Draw a watch region at least 24 pixels wide and tall.")
    scale = _scale(base)
    members = [photo["id"] for photo in photos]
    pixels = [region_pixels(library.blobs, photo, box, scale) for photo in photos]
    table = _pair_table(members, pixels)
    groups = _build_groups(mode, members, table, threshold)
    result_groups = []
    for group in groups:
        representative = _representative(mode, members, group, table)
        worst = None
        for pos, left in enumerate(group):
            for right in group[pos + 1:]:
                metrics = lookup_pair(table, left, right)
                if worst is None or metrics["similarity"] < worst["similarity"]:
                    worst = {"left": members[left], "right": members[right], **metrics}
        result_groups.append({
            "members": [members[index] for index in group],
            "representative": members[representative],
            "worst_pair": worst,
        })
    return {
        "mode": mode,
        "threshold": threshold,
        "photo_ids": members,
        "box": box,
        "scale": scale,
        "pairs": [
            {"left": members[left], "right": members[right], **metrics}
            for (left, right), metrics in table.items()
        ],
        "groups": result_groups,
    }


def difference_image(library, desk, data):
    ids = data.get("photo_ids")
    if not isinstance(ids, list) or len(ids) != 2:
        raise Invalid("Choose two photographs to compare.")
    photos = [model.select(desk["photos"], photo_id, "Photo") for photo_id in ids]
    if photos[0]["width"] != photos[1]["width"] or photos[0]["height"] != photos[1]["height"]:
        raise Invalid("The two photographs have different pixel dimensions.")
    box = model.rectangle(data.get("box"), photos[0]["width"], photos[0]["height"], "Watch region")
    scale = _scale(photos[0])
    reference, candidate = (region_pixels(library.blobs, photo, box, scale) for photo in photos)
    metrics = pair_metrics(reference, candidate)
    height, width = reference.shape[:2]
    shift_x, shift_y = metrics["shift"]
    aligned = np.empty_like(candidate)
    aligned[:] = reference
    src_x0, src_x1 = max(0, shift_x), min(width, width + shift_x)
    src_y0, src_y1 = max(0, shift_y), min(height, height + shift_y)
    aligned[max(0, -shift_y):min(height, height - shift_y),
            max(0, -shift_x):min(width, width - shift_x)] = \
        candidate[src_y0:src_y1, src_x0:src_x1]
    delta = np.abs(reference.astype(np.int16) - aligned.astype(np.int16)).max(axis=-1)
    heat = np.zeros((*delta.shape, 3), dtype=np.uint8)
    heat[:] = (38, 37, 48)
    changed = delta > 0
    heat[changed, 0] = np.minimum(255, 90 + delta[changed] * 4)
    heat[changed, 1] = 76
    heat[changed, 2] = 84
    rows, columns = GRID
    cell_h, cell_w = max(1, height // rows), max(1, width // columns)
    cell = metrics["max_cell"]
    cell_row, cell_column = divmod(cell, columns)
    cell_box = [cell_column * cell_w, cell_row * cell_h,
                width if cell_column == columns - 1 else (cell_column + 1) * cell_w,
                height if cell_row == rows - 1 else (cell_row + 1) * cell_h]
    canvas = Image.new("RGB", (width * 3 + 16, height + 34), "#e7e5de")
    draw = ImageDraw.Draw(canvas)
    tiles = (
        (Image.fromarray(reference), "Kept photo"),
        (Image.fromarray(aligned), "Other photo, aligned"),
        (Image.fromarray(heat), "Changed pixels"),
    )
    for index, (tile, caption) in enumerate(tiles):
        x = index * (width + 8)
        canvas.paste(tile, (x, 28))
        draw.text((x + 2, 8), caption, fill="#3b3b46")
        draw.rectangle((x, 28, x + width - 1, height + 27), outline="#9a97a8")
    outline_x = 2 * (width + 8)
    draw.rectangle((outline_x + cell_box[0], 28 + cell_box[1],
                    outline_x + cell_box[2] - 1, 28 + cell_box[3] - 1),
                   outline="#ffd166", width=2)
    return canvas, metrics
