"""Durable per-account state. Atomic replace for small files, append-only
for the post log. See design §9."""
import json, os

FORMAT_VERSION = 1

class ArchiveState:
    def __init__(self, account_dir: str):
        self.dir = os.path.join(account_dir, ".x-archive")
        os.makedirs(self.dir, exist_ok=True)
        self._manifest = os.path.join(self.dir, "manifest.json")
        self._posts = os.path.join(self.dir, "posts.jsonl")
        self._checkpoint = os.path.join(self.dir, "checkpoint.json")

    def _atomic_write(self, path: str, obj: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on POSIX

    def _read_json(self, path: str):
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def write_manifest(self, d: dict) -> None:
        d = {**d, "format_version": FORMAT_VERSION}
        self._atomic_write(self._manifest, d)

    def read_manifest(self):
        return self._read_json(self._manifest)

    def append_post(self, record: dict) -> None:
        with open(self._posts, "a") as f:
            f.write(json.dumps(record) + "\n")

    def read_posts(self) -> list:
        if not os.path.exists(self._posts):
            return []
        out = []
        with open(self._posts) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn final line from a crash; skip it
        return out

    def write_checkpoint(self, d: dict) -> None:
        self._atomic_write(self._checkpoint, d)

    def read_checkpoint(self):
        return self._read_json(self._checkpoint)

    def rendered_today(self, day: str) -> int:
        cp = self.read_checkpoint() or {}
        counts = cp.get("rendered_by_day", {})
        return int(counts.get(day, 0))

    def bump_rendered(self, day: str, n: int = 1) -> int:
        cp = self.read_checkpoint() or {}
        counts = cp.setdefault("rendered_by_day", {})
        counts[day] = int(counts.get(day, 0)) + n
        self.write_checkpoint(cp)
        return counts[day]
