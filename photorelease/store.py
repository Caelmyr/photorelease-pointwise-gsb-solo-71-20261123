import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from image_lab.validation import Conflict, Invalid

from . import model


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def atomic_write(path, data):
    temporary = path.with_name(f".{path.name}.{model.key()}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class BlobStore:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, data):
        digest = sha256(data)
        directory = self.root / digest[:2]
        directory.mkdir(exist_ok=True)
        path = directory / digest
        if not path.exists():
            atomic_write(path, data)
        return digest

    def read(self, digest):
        digest = model.blob_id(digest)
        path = self.root / digest[:2] / digest
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise Invalid("A stored image or output is missing.") from error


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.desks = self.root / "desks"
        self.issues = self.root / "issues"
        self.desks.mkdir(parents=True, exist_ok=True)
        self.issues.mkdir(parents=True, exist_ok=True)
        self.blobs = BlobStore(self.root / "blobs")
        self.lock = RLock()

    def _deskfile(self, key):
        return self.desks / (model.identifier(key) + ".json")

    def _issuefile(self, key):
        return self.issues / (model.identifier(key) + ".json")

    def list(self):
        with self.lock:
            summaries = [
                model.summarize(json.loads(path.read_bytes()))
                for path in self.desks.glob("*.json")
            ]
        return sorted(summaries, key=lambda item: item["updated_at"], reverse=True)

    def open(self, key):
        try:
            return json.loads(self._deskfile(key).read_bytes())
        except FileNotFoundError as error:
            raise Invalid("This desk was not found.") from error

    def add(self, desk):
        with self.lock:
            atomic_write(self._deskfile(desk["id"]), json_bytes(desk))
        return desk

    def mutate(self, key, revision, operation):
        revision = model.integer(revision, "Revision", 0, 2**53 - 1)
        with self.lock:
            desk = self.open(key)
            if desk["revision"] != revision:
                raise Conflict("The desk changed. Reload it before applying this edit.")
            operation(desk)
            desk["revision"] += 1
            desk["updated_at"] = model.now()
            atomic_write(self._deskfile(key), json_bytes(desk))
        return desk

    def save_issue(self, document):
        atomic_write(self._issuefile(document["id"]), json_bytes(document))

    def issue(self, desk, issue_id):
        model.select(desk["issues"], issue_id, "Issue")
        try:
            return json.loads(self._issuefile(issue_id).read_bytes())
        except FileNotFoundError as error:
            raise Invalid("This issue is missing from the library.") from error
