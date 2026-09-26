import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fresh(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def inventory(root):
    return [
        {"path": str(p.resolve()), "sha256": sha256(p)}
        for p in sorted(Path(root).rglob("*"))
        if p.is_file()
    ]


def verify(items, root=None):
    if not items or len({x["path"] for x in items}) != len(items):
        raise ValueError("Missing or duplicate inventory entries")
    for item in items:
        if not Path(item["path"]).is_file() or sha256(item["path"]) != item["sha256"]:
            raise ValueError("Locked file changed: " + item["path"])
    if root is not None:
        actual = {str(p.resolve()) for p in Path(root).rglob("*") if p.is_file()}
        if actual != {i["path"] for i in items}:
            raise ValueError("BIDS file set changed; re-audit and stage a new version")


def disjoint(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ValueError("Input and output directories must not overlap")
