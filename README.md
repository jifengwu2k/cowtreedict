# cowtreedict

An immutable, copy-on-write (COW) sorted dictionary for Python with **O(log n) order-statistic operations**.

## Why This Exists

No Python package on PyPI provides all four of these properties together:

| Library | Persistent | Sorted | Order-statistic | Hashable |
|---------|:---:|:---:|:---:|:---:|
| `dict` / `frozenset` | no / yes | no | no | no / yes |
| [`pyrsistent.PMap`](https://pypi.org/project/pyrsistent/) | yes | no | no | yes |
| [`sortedcontainers.SortedDict`](https://pypi.org/project/sortedcontainers/) | no | yes | yes | no |
| [`immutables.Map`](https://pypi.org/project/immutables/) (EdgeDB) | yes | no | no | no |
| **`cowtreedict.COWTreeDict`** | **yes** | **yes** | **yes** | **yes** |

`COWTreeDict` fills this gap. If you need a sorted dict that is also immutable, hashable, and supports positional access — this is it.

## Motivation

- **`sortedcontainers`** gives you sorted + order statistics, but it's mutable. Sharing state across versions requires explicit deep copies — O(n) per snapshot.
- **`pyrsistent`** gives you persistence + hashability, but it's hash-based and unordered. No sorted iteration, no "what's the k-th smallest key?".
- **`immutables`** (from the EdgeDB team) gives you a fast persistent mapping, but again unsorted and not even hashable.

If you want *persistent + sorted + positional access + hashable* in Python, you had to roll your own. Now you don't.

Languages like Clojure (`sorted-map`), Scala (`TreeMap`), and Haskell (`Data.Map`) have had this in their standard libraries for years. Python didn't — until now.

## Installation

```bash
pip install cowtreedict
```

## Example Usage

```python
from cowtreedict import COWTreeDict

# Construction (same interface as frozen_odict() plus lt)
d = COWTreeDict({'c': 3, 'a': 1, 'b': 2})

# Keys are always sorted
list(d)  # ['a', 'b', 'c']

# Mutations return new instances — the original is never modified
d2 = d.set('d', 4)
d3 = d2.delete('a')
list(d)   # ['a', 'b', 'c']     — unchanged
list(d3)  # ['b', 'c', 'd']

# Order-statistic operations in O(log n)
d.select(0)       # 'a' — smallest key
d.select(-1)      # 'c' — largest key
d.rank('b')       # 1   — number of keys < 'b'
d.peekitem(0)     # ('a', 1) — item at position 0
d.peekitem(-1)    # ('c', 3) — last item

# Range iteration in O(log n + k)
list(d.irange('a', 'b'))                            # ['a', 'b']
list(d.irange('a', 'c', inclusive=(False, False)))  # ['b']

# Hashable — can be used as dict keys or in sets
cache = {d: 'result'}
cache[COWTreeDict({'a': 1, 'b': 2, 'c': 3})]  # 'result'

# Structural sharing minimizes memory
# d and d2 share all nodes except those on the path to 'd'
```

## Use Cases

- **Functional-style programming** — chain transformations without defensive copying.
- **Undo/redo** — keep a stack of previous versions at near-zero cost.
- **Event sourcing / temporal versioning** — each event produces a new version; all versions are queryable.
- **Concurrent reads** — no locks needed since instances are immutable.
- **Sorted dicts as dict keys or set elements** — because `COWTreeDict` is hashable.
- **Competitive programming** — O(log n) rank and select without pulling in C extensions.

## API Reference

### Construction

| Method | Description | Time |
|--------|-------------|------|
| `COWTreeDict()` | Empty dict | O(1) |
| `COWTreeDict(mapping)` | From another mapping | O(n log n) |
| `COWTreeDict(iterable)` | From (key, value) pairs | O(n log n) |
| `COWTreeDict(mapping, lt=func)` | Custom comparison order | O(n log n) |

### COW-Mutating Methods

All return a **new instance**. The original is never modified.

| Method | Description | Time |
|--------|-------------|------|
| `d.set(key, value)` | Insert or replace a key | O(log n) |
| `d.delete(key)` | Remove a key (raises `KeyError` if absent) | O(log n) |
| `d.discard(key)` | Remove a key (returns self if absent) | O(log n) |
| `d.update(mapping_or_pairs, **kw)` | Merge mappings | O(m log(n+m)) |
| `d.pop(key[, default])` | Returns `(new_dict, value)` | O(log n) |
| `d.setdefault(key, val)` | Returns `(new_or_same_dict, value)` | O(log n) |
| `d.popitem(index=-1)` | Returns `(new_dict, key, value)` by position | O(log n) |
| `d.clear()` | Returns empty instance | O(1) |

### Mapping (Read) Methods

| Method | Description | Time |
|--------|-------------|------|
| `d[key]` | Get value by key | O(log n) |
| `key in d` | Membership test | O(log n) |
| `len(d)` | Number of items | O(1) |
| `iter(d)` | Iterate keys in sorted order | O(n) |
| `reversed(d)` | Iterate keys in reverse sorted order | O(n) |
| `d.keys()` | Sorted keys view | O(1) |
| `d.values()` | Values in key-sorted order view | O(1) |
| `d.items()` | Sorted (key, value) pairs view | O(1) |
| `d.get(key[, default])` | Get with default (inherited from Mapping) | O(log n) |
| `d == other` | Equality comparison | O(n) |
| `hash(d)` | Hash (cached after first call) | O(n) first, O(1) after |

### Order-Statistic Operations

| Method | Description | Time |
|--------|-------------|------|
| `d.select(index)` | Key at sorted position (negative indexing supported) | O(log n) |
| `d.rank(key)` | Number of keys strictly less than key | O(log n) |
| `d.peekitem(index=-1)` | `(key, value)` at sorted position | O(log n) |
| `d.bisect_left(key)` | Alias for `rank()` | O(log n) |
| `d.bisect_right(key)` | Number of keys ≤ key | O(log n) |

### Range Operations

| Method | Description | Time |
|--------|-------------|------|
| `d.irange(min, max, inclusive=(True, True))` | Iterate keys in range | O(log n + k) |
| `d.irange_items(min, max, inclusive=(True, True))` | Iterate (key, value) in range | O(log n + k) |

## How It Works

`COWTreeDict` is backed by an AVL tree augmented with subtree sizes for O(log n) positional access.

**Path copying** provides persistence: when a key is inserted or deleted, only the nodes on the path from the root to the affected leaf are copied (O(log n) nodes). All other nodes are shared between the old and new tree.

```
Original:           After d.set('f', 6):

      c                    c'
     / \                  / \
    a   e     →         a   e'       (only c, e, f are new nodes)
       / \                 / \
      d   (nil)           d   f      (a and d are shared)
```

This means:
- Each mutation allocates only O(log n) new node objects.
- Old versions remain valid and accessible with zero overhead.
- Memory usage grows linearly with the number of distinct mutations, not with the total number of versions.

## Part of the COW Family

`COWTreeDict` is designed alongside [`cowlist`](https://github.com/jifengwu2k/cowlist) to form a coherent family of persistent Python collections:

| Package | Type | Backing structure |
|---------|------|-------------------|
| [`cowlist`](https://github.com/jifengwu2k/cowlist) | `Sequence` | Copy-on-write list with O(1) slicing |
| **`cowtreedict`** | `Mapping` | AVL tree with path copying |

Both are immutable, hashable, and share the same conventions (`__new__`-only construction, cached `tuplehash`, COW mutation methods returning new instances).

## Dependencies

- [`tuplehash`](https://github.com/jifengwu2k/tuplehash) — Pure Python reimplementation of CPython's `tuplehash` for computing hash values without materializing intermediate tuples.

## Contributing

Contributions are welcome! Please submit pull requests or open issues on the GitHub repository.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
