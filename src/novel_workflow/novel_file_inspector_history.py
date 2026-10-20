"""Independent settings, review decisions and inspection history."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import tempfile
import uuid

from .novel_file_inspector import Inspection, InspectedFile


class InspectorStore:
    def __init__(self, app_root: str | Path):
        self.root = Path(app_root) / "novel_file_inspector"
        self.root.mkdir(parents=True, exist_ok=True)

    def _read(self, filename: str, default):
        p = self.root / filename
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, filename: str, value):
        destination = self.root / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(value, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)

    def cache(self, source, kind):
        key = self._identity(source, kind)
        return self._read("cache/" + key + ".json", {})

    def save_cache(self, source, kind, cache):
        (self.root / "cache").mkdir(exist_ok=True)
        key = self._identity(source, kind)
        self._write("cache/" + key + ".json", cache)

    def settings(self):
        return {"minimum": 1500, "missing": True, "numbers": True, "short": True,
                "duplicates": True, "size": True, **self._read("settings.json", {})}

    def save_settings(self, settings):
        self._write("settings.json", settings)

    @staticmethod
    def _identity(source, kind):
        from hashlib import sha256
        return sha256((kind + "\n" + str(Path(source).resolve()).casefold()).encode("utf-8")).hexdigest()

    def reviews(self, source, kind):
        return self._read("reviews.json", {}).get(self._identity(source, kind), {})

    def mark(self, inspection: Inspection, filename: str, decision: str):
        if decision not in ("keep", "excluded", "pending"):
            raise ValueError("Unknown review decision")
        row = next((r for r in inspection.files if not r.virtual and r.name == filename), None)
        if row is None or row.error:
            raise ValueError("Review requires a readable real file")
        db = self._read("reviews.json", {})
        items = db.setdefault(self._identity(inspection.source, inspection.kind), {})
        items[row.name] = {"decision": decision, "fingerprint": row.fingerprint}
        self._write("reviews.json", db)
        row.review, row.review_stale = decision, False

    def add_inspection(self, inspection: Inspection):
        if inspection.cancelled:
            return None
        ident = uuid.uuid4().hex
        payload = {"id": ident, "time": datetime.now(timezone.utc).isoformat(),
                   "source": inspection.source, "kind": inspection.kind,
                   "minimum": inspection.minimum, "summary": inspection.summary(),
                   "files": [asdict(row) for row in inspection.files]}
        folder = self.root / "inspections"
        folder.mkdir(exist_ok=True)
        self._write("inspections/" + ident + ".json", payload)
        entries = self._read("history.json", [])
        entries.insert(0, {k: payload[k] for k in ("id", "time", "source", "kind", "summary")})
        self._write("history.json", entries[:200])
        return ident

    def history(self):
        return self._read("history.json", [])

    def read_inspection(self, ident):
        if not ident.isalnum() or len(ident) != 32:
            raise ValueError("Invalid inspection identifier")
        payload = self._read("inspections/" + ident + ".json", None)
        if not payload:
            raise FileNotFoundError(ident)
        return Inspection(payload["source"], payload["kind"],
                          [InspectedFile(**f) for f in payload["files"]], payload["minimum"])

    def add_operation(self, operation, plan):
        db = self._read("operations.json", [])
        db.insert(0, {"time": datetime.now(timezone.utc).isoformat(),
                      "source": plan.source, "start": plan.start, "padding": plan.padding,
                      "change_heading": plan.change_heading,
                      "files": [asdict(f) for f in plan.files], **operation})
        self._write("operations.json", db[:200])

    def operations(self):
        return self._read("operations.json", [])
