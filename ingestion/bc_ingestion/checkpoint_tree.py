"""Bounded immutable B+ tree and mutation tracking for Blob checkpoint records."""

from bisect import bisect_right
from collections import OrderedDict
from collections.abc import MutableMapping, MutableSequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import weakref

from .manifest import CheckpointError


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class StorageLimits:
    node_entries: int = 32
    node_bytes: int = 65_536
    tree_depth: int = 8
    record_bytes: int = 32_768
    core_bytes: int = 131_072
    payload_bytes: int = 16_777_216
    segment_ops: int = 32
    segment_bytes: int = 262_144
    commit_ops: int = 256
    compact_after: int = 8
    replay_segments: int = 16
    replay_bytes: int = 4_194_304
    compaction_segments: int = 8
    compaction_nodes: int = 512
    compaction_bytes: int = 16_777_216
    list_page_items: int = 32
    cached_nodes: int = 256
    cached_records: int = 256
    execution_calls: int = 5_000
    execution_read_bytes: int = 67_108_864
    execution_write_bytes: int = 268_435_456
    execution_seconds: int = 110
    legacy_bytes: int = 8_388_608
    review_page: int = 100

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise CheckpointError("checkpoint-invalid-storage-limits")
        if (
            self.node_entries < 4 or self.record_bytes * 2 > self.node_bytes
            or self.compact_after >= self.replay_segments
            or self.commit_ops > self.segment_ops * self.compaction_segments
            or self.compact_after + self.compaction_segments > self.replay_segments
        ):
            raise CheckpointError("checkpoint-inconsistent-storage-limits")

    def format_limits(self):
        return {key: value for key, value in asdict(self).items()
                if not key.startswith(("execution_", "cached_")) and key != "review_page"}


class ImmutableTree:
    """Copy-on-write pages: compaction rewrites affected bounded pages, not a full index."""

    def __init__(self, objects, limits: StorageLimits):
        self.objects, self.limits = objects, limits
        self.cache = OrderedDict()
        self.written_nodes = 0
        self.written_bytes = 0

    def _load(self, value):
        if value is None:
            return {"kind": "leaf", "entries": []}
        if "kind" in value:
            return value
        key = value["sha256"]
        if key not in self.cache:
            node = json.loads(self.objects.get_reference(value, limit=self.limits.node_bytes))
            if node.get("kind") not in ("leaf", "branch"):
                raise CheckpointError("checkpoint-invalid-tree-node")
            entries = node.get("entries") if node["kind"] == "leaf" else node.get("children")
            if not isinstance(entries, list) or not entries or len(entries) > self.limits.node_entries:
                raise CheckpointError("checkpoint-invalid-tree-page")
            keys = [item[0] for item in entries]
            if any(not isinstance(key, str) for key in keys) or keys != sorted(set(keys)):
                raise CheckpointError("checkpoint-invalid-tree-order")
            self.cache[key] = node
            while len(self.cache) > self.limits.cached_nodes:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def get(self, root, key: str):
        current = root
        for _ in range(self.limits.tree_depth):
            node = self._load(current)
            if node["kind"] == "leaf":
                return next((value for found, value in node["entries"] if found == key), None)
            children = node["children"]
            index = max(0, bisect_right([item[0] for item in children], key) - 1)
            current = children[index][1]
        raise CheckpointError("checkpoint-tree-depth-exceeded")

    def scan(self, root, prefix: str, after: str = "", depth=0):
        if root is None:
            return
        if depth >= self.limits.tree_depth:
            raise CheckpointError("checkpoint-tree-depth-exceeded")
        node = self._load(root)
        if node["kind"] == "leaf":
            for key, value in node["entries"]:
                if key.startswith(prefix) and key > after:
                    yield key, value
            return
        lower, upper = max(prefix, after), prefix + "\U0010ffff"
        children = node["children"]
        for index, (minimum, child) in enumerate(children):
            following = children[index + 1][0] if index + 1 < len(children) else None
            if minimum > upper or (following is not None and following <= lower):
                continue
            yield from self.scan(child, prefix, after, depth + 1)

    def _split(self, node):
        field = "entries" if node["kind"] == "leaf" else "children"
        entries = node[field]
        # Child references have fixed-size wire bounds; dirty children are flushed later.
        size = len(encoded(node)) if node["kind"] == "leaf" else len(entries) * 512
        if len(entries) <= self.limits.node_entries and size <= self.limits.node_bytes:
            return [node] if entries else []
        if len(entries) < 2:
            raise CheckpointError("checkpoint-tree-entry-exceeds-page-bound")
        middle = len(entries) // 2
        return self._split({"kind": node["kind"], field: entries[:middle]}) + self._split({
            "kind": node["kind"], field: entries[middle:],
        })

    @staticmethod
    def _minimum(node):
        return node["entries"][0][0] if node["kind"] == "leaf" else node["children"][0][0]

    def _change(self, root, key, value, depth):
        if depth >= self.limits.tree_depth:
            raise CheckpointError("checkpoint-tree-depth-exceeded")
        node = self._load(root)
        if node["kind"] == "leaf":
            entries = [(k, v) for k, v in node["entries"] if k != key]
            if value is not None:
                entries.append((key, value))
            entries.sort(key=lambda item: item[0])
            return self._split({"kind": "leaf", "entries": entries})
        children = list(node["children"])
        index = max(0, bisect_right([item[0] for item in children], key) - 1)
        changed = self._change(children[index][1], key, value, depth + 1)
        children[index:index + 1] = [(self._minimum(child), child) for child in changed]
        return self._split({"kind": "branch", "children": children})

    def apply(self, root, operations):
        current = root
        for key, value in operations:
            if not isinstance(key, str) or not 1 <= len(key) <= 4096:
                raise CheckpointError("checkpoint-index-key-exceeds-bound")
            if value is not None and len(encoded([key, value])) > self.limits.record_bytes:
                raise CheckpointError("checkpoint-record-exceeds-bound")
            result = self._change(current, key, value, 0)
            if not result:
                current = None
            elif len(result) == 1:
                current = result[0]
            else:
                current = {"kind": "branch", "children": [(self._minimum(child), child) for child in result]}
        while current is not None and "kind" in current and current["kind"] == "branch" and len(current["children"]) == 1:
            current = current["children"][0][1]
        return current

    def flush(self, root, depth=0):
        if root is None or "kind" not in root:
            return root
        if depth >= self.limits.tree_depth:
            raise CheckpointError("checkpoint-tree-depth-exceeded")
        node = root
        if node["kind"] == "branch":
            node = {"kind": "branch", "children": [
                [minimum, self.flush(child, depth + 1)] for minimum, child in node["children"]
            ]}
        body = encoded(node)
        self.written_nodes += 1
        self.written_bytes += len(body)
        if (
            len(body) > self.limits.node_bytes
            or self.written_nodes > self.limits.compaction_nodes
            or self.written_bytes > self.limits.compaction_bytes
        ):
            raise CheckpointError("checkpoint-compaction-work-bound-exceeded")
        key = self.objects.put(body)
        reference = self.objects.reference(key)
        self.cache[key] = node
        while len(self.cache) > self.limits.cached_nodes:
            self.cache.popitem(last=False)
        return reference


def track(value, changed):
    if isinstance(value, LazyList):
        value.changed = changed
        return value
    if isinstance(value, dict):
        return TrackedDict(value, changed)
    if isinstance(value, list):
        return TrackedList(value, changed)
    return value


class TrackedDict(dict):
    def __init__(self, values=(), changed=lambda: None):
        self.changed = changed
        dict.__init__(self, ((key, track(value, changed)) for key, value in dict(values).items()))

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, track(value, self.changed))
        self.changed()

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        self.changed()

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key, *default):
        if key not in self:
            if default:
                return default[0]
            raise KeyError(key)
        result = self[key]
        del self[key]
        return result

    def popitem(self):
        key = next(reversed(self))
        return key, self.pop(key)

    def clear(self):
        if self:
            dict.clear(self)
            self.changed()

    def __ior__(self, value):
        self.update(value)
        return self

    def __deepcopy__(self, memo):
        return {deepcopy(key, memo): deepcopy(value, memo) for key, value in self.items()}


class TrackedList(list):
    def __init__(self, values=(), changed=lambda: None):
        self.changed = changed
        list.__init__(self, (track(value, changed) for value in values))

    def __setitem__(self, index, value):
        list.__setitem__(self, index, [track(v, self.changed) for v in value] if isinstance(index, slice)
                         else track(value, self.changed))
        self.changed()

    def __delitem__(self, index):
        list.__delitem__(self, index)
        self.changed()

    def append(self, value):
        list.append(self, track(value, self.changed))
        self.changed()

    def extend(self, values):
        list.extend(self, (track(value, self.changed) for value in values))
        self.changed()

    def insert(self, index, value):
        list.insert(self, index, track(value, self.changed))
        self.changed()

    def pop(self, index=-1):
        value = list.pop(self, index)
        self.changed()
        return value

    def clear(self):
        list.clear(self)
        self.changed()

    def remove(self, value):
        list.remove(self, value)
        self.changed()

    def reverse(self):
        list.reverse(self)
        self.changed()

    def sort(self, *args, **kwargs):
        list.sort(self, *args, **kwargs)
        self.changed()

    def __iadd__(self, values):
        self.extend(values)
        return self

    def __imul__(self, count):
        list.__imul__(self, count)
        self.changed()
        return self

    def __deepcopy__(self, memo):
        return [deepcopy(value, memo) for value in self]


class LazyList(MutableSequence):
    """Large sections/link lists validate on use, not on every job resume."""

    def __init__(self, objects, reference, length: int, changed=lambda: None):
        self.objects, self.reference, self.length, self.changed = objects, reference, length, changed
        self.value = None
        self.dirty = False
        if type(length) is not int or not 0 <= length <= 1_000_000:
            raise CheckpointError("checkpoint-invalid-payload-length")
        objects.validate_reference(reference)

    def _changed(self):
        self.dirty = True
        self.changed()

    def _read(self):
        if self.value is None:
            value = json.loads(self.objects.get_reference(self.reference, limit=self.objects.payload_limit))
            if not isinstance(value, list) or len(value) != self.length:
                raise CheckpointError("checkpoint-payload-shape-mismatch")
            self.value = TrackedList(value, self._changed)
        return self.value

    def __len__(self):
        return len(self.value) if self.value is not None else self.length

    def __getitem__(self, index):
        return self._read()[index]

    def __setitem__(self, index, value):
        self._read()[index] = value

    def __delitem__(self, index):
        del self._read()[index]

    def insert(self, index, value):
        self._read().insert(index, value)

    def __iter__(self):
        return iter(self._read())

    def __deepcopy__(self, memo):
        return deepcopy(list(self), memo)

    def __eq__(self, other):
        if isinstance(other, LazyList) and not self.dirty and not other.dirty:
            return self.reference["sha256"] == other.reference["sha256"] and len(self) == len(other)
        return list(self) == list(other) if isinstance(other, (list, LazyList, PagedList)) else False

    def wire(self):
        if self.dirty:
            self.reference = self.objects.reference(self.objects.put_json(list(self._read())))
            self.length, self.dirty = len(self.value), False
        return {"$payload": self.reference, "length": self.length}


class RecordMap(MutableMapping):
    def __init__(self, state, path: str, length=0):
        self.owner, self.path, self.length = state, path, length
        self.prefix = "m/" + path + "/"
        self.cache = OrderedDict()
        self.dirty = {}
        self.old = {}
        self.active = weakref.WeakValueDictionary()

    def _wrap(self, key, value):
        def changed():
            if self.active.get(key) is wrapped:
                self._touch(key, wrapped)
        wrapped = track(value, changed)
        if isinstance(wrapped, (TrackedDict, TrackedList, LazyList)):
            self.active[key] = wrapped
        return wrapped

    def _key(self, key):
        if not isinstance(key, str):
            raise CheckpointError("checkpoint-record-keys-must-be-strings")
        return self.prefix + key

    def _touch(self, key, value):
        if key not in self.old:
            self.old[key] = self.owner.engine.get(self._key(key))
        self.dirty[key] = value
        self.cache[key] = value

    def __getitem__(self, key):
        if key in self.dirty:
            if self.dirty[key] is None:
                raise KeyError(key)
            return self.dirty[key]
        if key not in self.cache:
            wrapped = self.active.get(key)
            if wrapped is None:
                raw = self.owner.engine.get(self._key(key))
                if raw is None:
                    raise KeyError(key)
                value = self.owner.decode_record(self.path, raw)
                wrapped = self._wrap(key, value)
            self.cache[key] = wrapped
        self.cache.move_to_end(key)
        while len(self.cache) > self.owner.limits.cached_records:
            self.cache.popitem(last=False)
        return self.cache[key]

    def __setitem__(self, key, value):
        exists = key in self
        wrapped = self._wrap(key, value)
        self._touch(key, wrapped)
        if not exists:
            self.length += 1

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        self._touch(key, None)
        self.active.pop(key, None)
        self.cache.pop(key, None)
        self.length -= 1

    def __iter__(self):
        keys = (key[len(self.prefix):] for key, _ in self.owner.engine.scan(self.prefix))
        seen = set()
        for key in keys:
            seen.add(key)
            if key not in self.dirty or self.dirty[key] is not None:
                yield key
        for key, value in list(self.dirty.items()):
            if value is not None and key not in seen:
                yield key

    def __len__(self):
        return self.length

    def __contains__(self, key):
        if key in self.dirty:
            return self.dirty[key] is not None
        return key in self.cache or self.owner.engine.get(self._key(key)) is not None

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def find_url(self, url):
        key = self.owner.engine.get("u/" + url)
        return self.get(key) if key else None

    def reverse_values(self, targets):
        found = {key for key, value in self.dirty.items() if value in targets}
        for target in targets:
            for _, key in self.owner.engine.scan("z/" + target + "\0"):
                if self.get(key) == target:
                    found.add(key)
        return iter(sorted(found))

    def find_duplicate(self, document, excluded):
        key = self.owner.duplicate_key(document.url, document.content_hash, document.metadata)
        ids = list(self.dirty) + list(self.owner.engine.get(key) or [])
        for identifier in ids:
            if identifier == excluded:
                continue
            entry = self.get(identifier)
            if not entry or not entry["versions"]:
                continue
            version = entry["versions"][-1]
            value = version["document"]
            if version["status"] not in ("withdrawn", "quarantined", "duplicate", "superseded") and (
                self.owner.duplicate_key(entry["url"], value["content_hash"], value.get("metadata", {})) == key
            ):
                return identifier
        return None

    def flush(self):
        for key, value in list(self.dirty.items()):
            raw = self.owner.encode_record(self.path, value) if value is not None else None
            self.owner.index_record(self.path, key, self.old.get(key), raw)
            self.owner.engine.set(self._key(key), raw)

    def acknowledge(self):
        self.dirty.clear()
        self.old.clear()
        while len(self.cache) > self.owner.limits.cached_records:
            self.cache.popitem(last=False)


class PagedList(MutableSequence):
    """Append-oriented audit/seed lists; updating one tail never rewrites the history."""

    def __init__(self, state, path, length=0):
        self.owner, self.path, self.length = state, path, length
        self.pages = RecordMap(state, "list:" + path, (length + state.limits.list_page_items - 1) // state.limits.list_page_items)

    def __len__(self):
        return self.length

    def _position(self, index):
        if index < 0:
            index += self.length
        if not 0 <= index < self.length:
            raise IndexError(index)
        return divmod(index, self.owner.limits.list_page_items)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.length))]
        page, position = self._position(index)
        return self.pages[f"{page:012d}"][position]

    def __setitem__(self, index, value):
        page, position = self._position(index)
        self.pages[f"{page:012d}"][position] = value

    def __delitem__(self, index):
        raise CheckpointError("checkpoint-history-deletion-requires-a-separate-reviewed-migration")

    def insert(self, index, value):
        if index != self.length:
            raise CheckpointError("checkpoint-history-is-append-only")
        page = self.length // self.owner.limits.list_page_items
        values = self.pages.setdefault(f"{page:012d}", [])
        values.append(value)
        self.length += 1

    def __iter__(self):
        for index in range(self.length):
            yield self[index]

    def __eq__(self, other):
        return list(self) == list(other) if isinstance(other, (list, LazyList, PagedList)) else False
