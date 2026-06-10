# An immutable, copy-on-write (COW) sorted dictionary with order-statistic operations
# Copyright (c) 2026 Jifeng Wu
# Licensed under the Apache License. See LICENSE file in the project root for full license information.
from typing import Iterator, Mapping, Reversible, TypeVar, Generic, Callable, Optional, Tuple, Iterable, Union
import operator

from tuplehash import tuplehash

KT = TypeVar('KT')
VT = TypeVar('VT')
SelfCOWTreeDict = TypeVar('SelfCOWTreeDict', bound='COWTreeDict')


class Node(Generic[KT, VT]):
    """Internal AVL tree node. Shared between COWTreeDict instances via path copying."""
    __slots__ = ('key', 'value', 'left', 'right', 'height', 'size')

    def __init__(self, key, value, left=None, right=None):
        # type: (KT, VT, Optional[Node[KT, VT]], Optional[Node[KT, VT]]) -> None
        self.key = key
        self.value = value
        self.left = left
        self.right = right
        self.height = 1 + max(node_height(left), node_height(right))
        self.size = 1 + node_size(left) + node_size(right)


def node_height(node):
    # type: (Optional[Node]) -> int
    return node.height if node else 0


def node_size(node):
    # type: (Optional[Node]) -> int
    return node.size if node else 0


def balance_factor(node):
    # type: (Node) -> int
    return node_height(node.left) - node_height(node.right)


def rebalance(key, value, left, right):
    # type: (KT, VT, Optional[Node], Optional[Node]) -> Node
    bf = node_height(left) - node_height(right)
    if bf > 1:
        if balance_factor(left) < 0:
            lr = left.right
            left = Node(lr.key, lr.value,
                        Node(left.key, left.value, left.left, lr.left),
                        lr.right)
        return Node(left.key, left.value,
                    left.left,
                    Node(key, value, left.right, right))
    elif bf < -1:
        if balance_factor(right) > 0:
            rl = right.left
            right = Node(rl.key, rl.value,
                         rl.left,
                         Node(right.key, right.value, rl.right, right.right))
        return Node(right.key, right.value,
                    Node(key, value, left, right.left),
                    right.right)
    return Node(key, value, left, right)


def min_key_value(node):
    # type: (Node) -> Tuple
    while node.left:
        node = node.left
    return node.key, node.value


def tree_insert(node, key, value, lt):
    # type: (Optional[Node], KT, VT, Callable) -> Tuple[Node, bool]
    """Path-copy insert. Returns (new_root, was_new_key)."""
    if node is None:
        return Node(key, value), True

    if lt(key, node.key):
        new_left, inserted = tree_insert(node.left, key, value, lt)
        return rebalance(node.key, node.value, new_left, node.right), inserted
    elif lt(node.key, key):
        new_right, inserted = tree_insert(node.right, key, value, lt)
        return rebalance(node.key, node.value, node.left, new_right), inserted
    else:
        return Node(node.key, value, node.left, node.right), False


def tree_delete(node, key, lt):
    # type: (Optional[Node], KT, Callable) -> Tuple[Optional[Node], bool]
    """Path-copy delete. Returns (new_root, was_deleted)."""
    if node is None:
        return None, False

    if lt(key, node.key):
        new_left, deleted = tree_delete(node.left, key, lt)
        if not deleted:
            return node, False
        return rebalance(node.key, node.value, new_left, node.right), True
    elif lt(node.key, key):
        new_right, deleted = tree_delete(node.right, key, lt)
        if not deleted:
            return node, False
        return rebalance(node.key, node.value, node.left, new_right), True
    else:
        if not node.left:
            return node.right, True
        if not node.right:
            return node.left, True
        succ_key, succ_value = min_key_value(node.right)
        new_right, _ = tree_delete(node.right, succ_key, lt)
        return rebalance(succ_key, succ_value, node.left, new_right), True


def iter_forward_nodes(node):
    # type: (Optional[Node]) -> Iterator[Node]
    stack = []
    cur = node
    while cur or stack:
        while cur:
            stack.append(cur)
            cur = cur.left
        cur = stack.pop()
        yield cur
        cur = cur.right


def iter_backward_nodes(node):
    # type: (Optional[Node]) -> Iterator[Node]
    stack = []
    cur = node
    while cur or stack:
        while cur:
            stack.append(cur)
            cur = cur.right
        cur = stack.pop()
        yield cur
        cur = cur.left


class COWTreeDict(Mapping[KT, VT], Reversible[KT]):
    """An immutable, copy-on-write (COW) sorted dictionary implementation.

    This class provides a persistent sorted mapping with copy-on-write semantics,
    where all mutating operations return new instances rather than modifying in-place.
    The implementation uses an AVL tree with path copying, sharing unchanged subtrees
    between related instances for minimal memory overhead.

    Key Features:
        - Immutability: All operations return new instances, never modify in-place.
        - Copy-on-write: Underlying tree nodes are shared until modifications are needed.
        - Sorted: Keys are always maintained in sorted order.
        - Order statistics: O(log n) positional access (select k-th key, find rank of key).
        - Mapping protocol: Full implementation of ``collections.abc.Mapping``.
        - Hashable: Instances can be used as set elements and dict keys (when keys/values are hashable).

    Performance Characteristics:
        - Lookup: O(log n)
        - Insert/delete: O(log n), allocating only O(log n) new nodes
        - Iteration: O(n)
        - Select by position: O(log n)
        - Rank query: O(log n)
        - Range iteration: O(log n + k) where k is the number of items yielded

    Example Usage:
        >>> d = COWTreeDict({'c': 3, 'a': 1, 'b': 2})
        >>> d2 = d.set('d', 4)      # Returns new instance; d is unchanged
        >>> d3 = d2.delete('a')     # Returns new instance; d2 is unchanged
        >>> list(d3)
        ['b', 'c', 'd']

    Notes:
        - Instances cache their hash value after first computation.
        - Tree nodes are shared between instances until mutations occur (path copying).
        - Construction accepts the same arguments as ``dict()``.
        - Custom sort order is supported via the ``lt`` parameter.

    Type Variables:
        KT: The key type.
        VT: The value type.
    """
    __slots__ = ('root', 'len', 'lt', 'hash')

    def __new__(cls, key_value_mapping_or_key_value_pairs=(), lt=operator.lt, **kwargs):
        # type: (type[SelfCOWTreeDict], Union[Mapping[KT, VT], Iterable[Tuple[KT, VT]]], Callable[[KT, KT], bool], **object) -> SelfCOWTreeDict
        """Create a new COWTreeDict instance.

        Args:
            key_value_mapping_or_key_value_pairs: A mapping or an iterable of
                (key, value) pairs. Defaults to empty.
            lt: A function of two arguments used to compare keys. Return True
                if the first argument is less than the second.
                Defaults to operator.lt.
            **kwargs: Additional key-value pairs to include.

        Returns:
            New COWTreeDict instance containing the given items in sorted key order.

        Raises:
            ValueError: If the first argument is not a mapping or iterable of pairs.
        """
        inst = object.__new__(cls)
        inst.root = None
        inst.len = 0
        inst.lt = lt
        inst.hash = None
        root = None
        count = 0
        if isinstance(key_value_mapping_or_key_value_pairs, Mapping):
            for k, v in key_value_mapping_or_key_value_pairs.items():
                root, inserted = tree_insert(root, k, v, inst.lt)
                if inserted:
                    count += 1
        elif isinstance(key_value_mapping_or_key_value_pairs, Iterable):
            for k, v in key_value_mapping_or_key_value_pairs:
                root, inserted = tree_insert(root, k, v, inst.lt)
                if inserted:
                    count += 1
        else:
            raise ValueError(
                'key_value_mapping_or_key_value_pairs '
                'must be Union[Mapping[K, V], Iterable[Tuple[K, V]]]'
            )
        for k, v in kwargs.items():
            root, inserted = tree_insert(root, k, v, inst.lt)
            if inserted:
                count += 1
        inst.root = root
        inst.len = count
        return inst

    @classmethod
    def from_root(cls, root, length, lt_func):
        # type: (type[SelfCOWTreeDict], Optional[Node], int, Callable[[KT, KT], bool]) -> SelfCOWTreeDict
        inst = object.__new__(cls)
        inst.root = root
        inst.len = length
        inst.lt = lt_func
        inst.hash = None
        return inst

    def find_node(self, key):
        # type: (SelfCOWTreeDict, KT) -> Optional[Node[KT, VT]]
        cur = self.root
        while cur:
            if self.lt(key, cur.key):
                cur = cur.left
            elif self.lt(cur.key, key):
                cur = cur.right
            else:
                return cur
        return None

    # COW-mutating methods

    def set(self, key, value):
        # type: (SelfCOWTreeDict, KT, VT) -> SelfCOWTreeDict
        """Return new instance with key mapped to value. O(log n)

        If key already exists, its value is replaced. The original is unchanged.
        Only O(log n) new nodes are allocated; all other nodes are shared.

        Args:
            key: The key to set.
            value: The value to associate with key.

        Returns:
            New instance with the key-value pair added or updated.
        """
        new_root, inserted = tree_insert(self.root, key, value, self.lt)
        new_len = self.len + (1 if inserted else 0)
        return self.from_root(new_root, new_len, self.lt)

    def delete(self, key):
        # type: (SelfCOWTreeDict, KT) -> SelfCOWTreeDict
        """Return new instance with key removed. O(log n)

        The original is unchanged.

        Args:
            key: The key to remove.

        Returns:
            New instance without the specified key.

        Raises:
            KeyError: If key is not present.
        """
        new_root, deleted = tree_delete(self.root, key, self.lt)
        if not deleted:
            raise KeyError(key)
        return self.from_root(new_root, self.len - 1, self.lt)

    def discard(self, key):
        # type: (SelfCOWTreeDict, KT) -> SelfCOWTreeDict
        """Return new instance with key removed, or self if key is absent. O(log n)

        Args:
            key: The key to remove.

        Returns:
            New instance without the key, or self if key was not present.
        """
        new_root, deleted = tree_delete(self.root, key, self.lt)
        if not deleted:
            return self
        return self.from_root(new_root, self.len - 1, self.lt)

    def update(self, key_value_mapping_or_key_value_pairs=(), **kwargs):
        # type: (SelfCOWTreeDict, Union[Mapping[KT, VT], Iterable[Tuple[KT, VT]]], **object) -> SelfCOWTreeDict
        """Return new instance with additional/updated mappings. O(m log(n+m))

        Accepts a mapping or iterable of (key, value) pairs plus keyword args.
        The original is unchanged.

        Args:
            key_value_mapping_or_key_value_pairs: A mapping or iterable of
                (key, value) pairs. Defaults to empty.
            **kwargs: Additional key-value pairs.

        Returns:
            New instance with the merged key-value pairs.

        Raises:
            ValueError: If the first argument is not a mapping or iterable of pairs.
        """
        root = self.root
        count = self.len
        any_item = False
        if isinstance(key_value_mapping_or_key_value_pairs, Mapping):
            for k, v in key_value_mapping_or_key_value_pairs.items():
                any_item = True
                root, inserted = tree_insert(root, k, v, self.lt)
                if inserted:
                    count += 1
        elif isinstance(key_value_mapping_or_key_value_pairs, Iterable):
            for k, v in key_value_mapping_or_key_value_pairs:
                any_item = True
                root, inserted = tree_insert(root, k, v, self.lt)
                if inserted:
                    count += 1
        else:
            raise ValueError(
                'key_value_mapping_or_key_value_pairs '
                'must be Union[Mapping[K, V], Iterable[Tuple[K, V]]]'
            )
        for k, v in kwargs.items():
            any_item = True
            root, inserted = tree_insert(root, k, v, self.lt)
            if inserted:
                count += 1
        if not any_item:
            return self
        return self.from_root(root, count, self.lt)

    _MISSING = object()

    def pop(self, key, default=_MISSING):
        # type: (SelfCOWTreeDict, KT, VT) -> Tuple[SelfCOWTreeDict, VT]
        """Return (new_instance_without_key, value). O(log n)

        If key is not found and a default is given, returns (self, default).
        If key is not found and no default is given, raises KeyError.

        Args:
            key: The key to remove and return.
            default: Optional default value if key is absent.

        Returns:
            Tuple of (new instance without key, removed value).

        Raises:
            KeyError: If key is not present and no default given.
        """
        node = self.find_node(key)
        if node is None:
            if default is not self._MISSING:
                return self, default
            raise KeyError(key)
        value = node.value
        new_root, _ = tree_delete(self.root, key, self.lt)
        return self.from_root(new_root, self.len - 1, self.lt), value

    def setdefault(self, key, default=None):
        # type: (SelfCOWTreeDict, KT, VT) -> Tuple[SelfCOWTreeDict, VT]
        """Return (new_or_same_instance, value_for_key). O(log n)

        If key is present, returns (self, existing_value).
        If key is absent, returns (new_instance_with_key, default).

        Args:
            key: The key to look up or insert.
            default: Value to insert if key is absent (default None).

        Returns:
            Tuple of (instance, value for key).
        """
        node = self.find_node(key)
        if node is not None:
            return self, node.value
        new_root, _ = tree_insert(self.root, key, default, self.lt)
        return self.from_root(new_root, self.len + 1, self.lt), default

    def popitem(self, index=-1):
        # type: (SelfCOWTreeDict, int) -> Tuple[SelfCOWTreeDict, KT, VT]
        """Return (new_instance, key, value) for the item at the given position. O(log n)

        Default pops the last (largest) item.

        Args:
            index: Sorted position to pop (supports negative indexing).

        Returns:
            Tuple of (new instance without the item, key, value).

        Raises:
            IndexError: If index is out of range.
        """
        k, v = self.peekitem(index)
        new_root, _ = tree_delete(self.root, k, self.lt)
        return self.from_root(new_root, self.len - 1, self.lt), k, v

    def clear(self):
        # type: (SelfCOWTreeDict) -> SelfCOWTreeDict
        """Return an empty new instance. O(1)

        Returns:
            Empty COWTreeDict with the same lt function.
        """
        return self.from_root(None, 0, self.lt)

    # Mapping non-mutating methods

    def __getitem__(self, key):
        # type: (SelfCOWTreeDict, KT) -> VT
        node = self.find_node(key)
        if node is None:
            raise KeyError(key)
        return node.value

    def __contains__(self, key):
        # type: (SelfCOWTreeDict, object) -> bool
        return self.find_node(key) is not None

    def __len__(self):
        # type: (SelfCOWTreeDict) -> int
        return self.len

    def __iter__(self):
        # type: (SelfCOWTreeDict) -> Iterator[KT]
        for node in iter_forward_nodes(self.root):
            yield node.key

    def __reversed__(self):
        # type: (SelfCOWTreeDict) -> Iterator[KT]
        for node in iter_backward_nodes(self.root):
            yield node.key

    def __bool__(self):
        # type: (SelfCOWTreeDict) -> bool
        return self.len > 0

    def __eq__(self, other):
        # type: (SelfCOWTreeDict, object) -> bool
        if isinstance(other, COWTreeDict):
            if len(self) != len(other):
                return False
            return all(
                not self.lt(k1, k2) and not self.lt(k2, k1) and v1 == v2
                for (k1, v1), (k2, v2) in zip(self.items(), other.items())
            )
        if isinstance(other, Mapping):
            if len(self) != len(other):
                return False
            return all(k in other and self[k] == other[k] for k in self)
        return NotImplemented

    def __hash__(self):
        # type: (SelfCOWTreeDict) -> int
        if self.hash is not None:
            return self.hash
        else:
            hash_value = tuplehash(self.items(), self.len)
            self.hash = hash_value
            return hash_value

    def __repr__(self):
        # type: (SelfCOWTreeDict) -> str
        return '%s({%s})' % (
            self.__class__.__name__,
            ', '.join('%r: %r' % (k, v) for k, v in self.items())
        )

    # Order-statistic operations

    def select(self, index):
        # type: (SelfCOWTreeDict, int) -> KT
        """Return the key at the given sorted position. O(log n)

        Supports negative indexing (-1 is the last/largest key).

        Args:
            index: 0-based sorted position (negative indexing supported).

        Returns:
            The key at the given position.

        Raises:
            IndexError: If index is out of range.
        """
        if index < 0:
            index += self.len
        if not (0 <= index < self.len):
            raise IndexError('index %d out of range for size %d' % (index, self.len))
        cur = self.root
        while cur:
            left_sz = node_size(cur.left)
            if index < left_sz:
                cur = cur.left
            elif index > left_sz:
                index -= left_sz + 1
                cur = cur.right
            else:
                return cur.key
        raise IndexError('index out of range')

    def rank(self, key):
        # type: (SelfCOWTreeDict, KT) -> int
        """Return the number of keys strictly less than key. O(log n)

        The key does not need to be present in the dict.

        Args:
            key: The key to query rank for.

        Returns:
            Number of keys strictly less than key.
        """
        result = 0
        cur = self.root
        while cur:
            if self.lt(cur.key, key):
                result += node_size(cur.left) + 1
                cur = cur.right
            else:
                cur = cur.left
        return result

    def peekitem(self, index=-1):
        # type: (SelfCOWTreeDict, int) -> Tuple[KT, VT]
        """Return the (key, value) pair at the given sorted position. O(log n)

        Default is the last (largest) item. Supports negative indexing.

        Args:
            index: 0-based sorted position (negative indexing supported).

        Returns:
            Tuple of (key, value) at the given position.

        Raises:
            IndexError: If index is out of range.
        """
        if index < 0:
            index += self.len
        if not (0 <= index < self.len):
            raise IndexError('index %d out of range for size %d' % (index, self.len))
        cur = self.root
        while cur:
            left_sz = node_size(cur.left)
            if index < left_sz:
                cur = cur.left
            elif index > left_sz:
                index -= left_sz + 1
                cur = cur.right
            else:
                return cur.key, cur.value
        raise IndexError('index out of range')

    def bisect_left(self, key):
        # type: (SelfCOWTreeDict, KT) -> int
        """Return the number of keys strictly less than key. O(log n)

        Alias for rank().

        Args:
            key: The key to query.

        Returns:
            Number of keys strictly less than key.
        """
        return self.rank(key)

    def bisect_right(self, key):
        # type: (SelfCOWTreeDict, KT) -> int
        """Return the number of keys less than or equal to key. O(log n)

        Args:
            key: The key to query.

        Returns:
            Number of keys less than or equal to key.
        """
        result = 0
        cur = self.root
        while cur:
            if self.lt(key, cur.key):
                cur = cur.left
            else:
                result += node_size(cur.left) + 1
                cur = cur.right
        return result

    # Range operations

    def irange(self, minimum=None, maximum=None, inclusive=(True, True)):
        # type: (SelfCOWTreeDict, Optional[KT], Optional[KT], Tuple[bool, bool]) -> Iterator[KT]
        """Iterate over keys in the range [minimum, maximum]. O(log n + k)

        Args:
            minimum: Lower bound (None means no lower bound).
            maximum: Upper bound (None means no upper bound).
            inclusive: Tuple of (include_min, include_max). Default (True, True).

        Yields:
            Keys in sorted order within the specified range.
        """
        for node in self.irange_nodes(minimum, maximum, inclusive):
            yield node.key

    def irange_items(self, minimum=None, maximum=None, inclusive=(True, True)):
        # type: (SelfCOWTreeDict, Optional[KT], Optional[KT], Tuple[bool, bool]) -> Iterator[Tuple[KT, VT]]
        """Like irange(), but yields (key, value) pairs. O(log n + k)

        Args:
            minimum: Lower bound (None means no lower bound).
            maximum: Upper bound (None means no upper bound).
            inclusive: Tuple of (include_min, include_max). Default (True, True).

        Yields:
            (key, value) pairs in sorted key order within the specified range.
        """
        for node in self.irange_nodes(minimum, maximum, inclusive):
            yield node.key, node.value

    def irange_nodes(self, minimum, maximum, inclusive):
        # type: (SelfCOWTreeDict, Optional[KT], Optional[KT], Tuple[bool, bool]) -> Iterator[Node]
        if self.root is None:
            return
        stack = []
        cur = self.root
        while cur or stack:
            while cur:
                stack.append(cur)
                if minimum is not None and not self.lt(cur.key, minimum):
                    cur = cur.left
                elif minimum is not None:
                    cur = None
                else:
                    cur = cur.left
            if not stack:
                return
            cur = stack.pop()
            if minimum is not None:
                if inclusive[0]:
                    if self.lt(cur.key, minimum):
                        cur = cur.right
                        continue
                else:
                    if not self.lt(minimum, cur.key):
                        cur = cur.right
                        continue
            if maximum is not None:
                if inclusive[1]:
                    if self.lt(maximum, cur.key):
                        return
                else:
                    if not self.lt(cur.key, maximum):
                        return
            yield cur
            cur = cur.right

    # Views

    def keys(self):
        # type: (SelfCOWTreeDict) -> KeysView
        """Return a view of keys in sorted order."""
        return KeysView(self)

    def values(self):
        # type: (SelfCOWTreeDict) -> ValuesView
        """Return a view of values in key-sorted order."""
        return ValuesView(self)

    def items(self):
        # type: (SelfCOWTreeDict) -> ItemsView
        """Return a view of (key, value) pairs in key-sorted order."""
        return ItemsView(self)


class KeysView(object):
    __slots__ = ('mapping',)

    def __init__(self, mapping):
        self.mapping = mapping

    def __iter__(self):
        return iter(self.mapping)

    def __reversed__(self):
        return reversed(self.mapping)

    def __len__(self):
        return len(self.mapping)

    def __contains__(self, key):
        return key in self.mapping

    def __repr__(self):
        return 'KeysView(%r)' % list(self)


class ValuesView(object):
    __slots__ = ('mapping',)

    def __init__(self, mapping):
        self.mapping = mapping

    def __iter__(self):
        for node in iter_forward_nodes(self.mapping.root):
            yield node.value

    def __reversed__(self):
        for node in iter_backward_nodes(self.mapping.root):
            yield node.value

    def __len__(self):
        return len(self.mapping)

    def __repr__(self):
        return 'ValuesView(%r)' % list(self)


class ItemsView(object):
    __slots__ = ('mapping',)

    def __init__(self, mapping):
        self.mapping = mapping

    def __iter__(self):
        for node in iter_forward_nodes(self.mapping.root):
            yield node.key, node.value

    def __reversed__(self):
        for node in iter_backward_nodes(self.mapping.root):
            yield node.key, node.value

    def __len__(self):
        return len(self.mapping)

    def __contains__(self, item):
        if not isinstance(item, tuple) or len(item) != 2:
            return False
        k, v = item
        try:
            return self.mapping[k] == v
        except KeyError:
            return False

    def __repr__(self):
        return 'ItemsView(%r)' % list(self)
