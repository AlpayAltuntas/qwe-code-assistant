"""Unified intermediate representation for the mapping engine.

Every source format (EDIFACT, UBL, CII) converts into the same `Node`
tree via a small per-format adapter (`edifact.to_ir`, `xmlmap.to_ir`),
and every field-addressing/extraction operation the mapping tool needs
— "what fields exist", "what's this field's value on a *different*
document" — is implemented exactly once here, against that tree, rather
than once per format.

The key move that makes one tree shape work for both segment-based
formats (EDIFACT) and genuinely nested ones (XML): EDIFACT's
element/component *positions* become synthetic child tags ("e0.c0",
"e1.c2") under a segment node, so a leaf is always addressed the same
way regardless of source format — by (parent node's tag, this node's
tag, occurrence of that pair within the current scope). EDIFACT's line
items (segments between LIN markers — a *sibling-range* concept, not
real nesting) get wrapped into a synthetic container node at IR-build
time (see edifact.to_ir), so repeating-group detection here only ever
has to deal with genuine subtree containment, uniformly.
"""

from dataclasses import dataclass, field


@dataclass(eq=False)  # identity equality/hash — same node twice in a
# tree (e.g. two segments with identical content) must stay distinguishable.
class Node:
    tag: str
    value: str | None = None  # leaf text; None for container nodes
    children: list["Node"] = field(default_factory=list)


def _iter_all(node: Node):
    yield node
    for child in node.children:
        yield from _iter_all(child)


def leaves(node: Node) -> list[Node]:
    """Every descendant with a non-None value, in document order."""
    return [n for n in _iter_all(node) if n.value is not None]


def build_parent_map(root: Node) -> dict[Node, Node]:
    return {child: parent for parent in _iter_all(root) for child in parent.children}


@dataclass
class Scope:
    """Precomputed once per document, reused for both describing the
    field picker and resolving a saved mapping's addresses."""

    header_leaves: list[Node]
    line_group_leaves: list[list[Node]]
    parent_map: dict[Node, Node]


def build_scope(root: Node, line_tag: str) -> Scope:
    """Finds every node tagged `line_tag` anywhere in the tree and treats
    each as one repeating line-item group (its own subtree's leaves);
    everything else is header scope."""
    parent_map = build_parent_map(root)
    line_nodes = [n for n in _iter_all(root) if n.tag == line_tag]
    line_node_set = set(line_nodes)

    def is_within_a_line(n: Node) -> bool:
        cur: Node | None = n
        while cur is not None:
            if cur in line_node_set:
                return True
            cur = parent_map.get(cur)
        return False

    header_leaves = [lf for lf in leaves(root) if not is_within_a_line(lf)]
    line_group_leaves = [leaves(n) for n in line_nodes]
    return Scope(header_leaves=header_leaves, line_group_leaves=line_group_leaves, parent_map=parent_map)


def _field_key(node: Node, parent_map: dict[Node, Node]) -> tuple[str, str]:
    parent = parent_map.get(node)
    return (parent.tag if parent is not None else "", node.tag)


def flatten_fields(nodes: list[Node], parent_map: dict[Node, Node]) -> list[dict]:
    """Every leaf in `nodes`, addressed by (parent tag, own tag,
    occurrence-of-that-pair) — powers the mapping UI's field pickers."""
    occurrence_counts: dict[tuple[str, str], int] = {}
    fields: list[dict] = []
    for node in nodes:
        key = _field_key(node, parent_map)
        occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
        occurrence = occurrence_counts[key]
        parent_tag, tag = key
        value = node.value or ""
        fields.append(
            {
                "parent_tag": parent_tag,
                "tag": tag,
                "occurrence": occurrence,
                "label": f"{parent_tag}/{tag}#{occurrence} = {value or '(empty)'}",
                "value": value,
            }
        )
    return fields


def extract_by_ref(nodes: list[Node], parent_map: dict[Node, Node], ref: dict) -> str | None:
    """Inverse of flatten_fields: given the same (parent_tag, tag,
    occurrence) address resolved against a *different* document's leaf
    list, returns that document's value — or None if it doesn't have a
    matching field. This is what lets a saved mapping generalize: the
    address is re-resolved against whatever document it's applied to,
    not baked to a fixed position."""
    target_key = (ref.get("parent_tag"), ref.get("tag"))
    occurrence = ref.get("occurrence")
    if occurrence is None or target_key[0] is None or target_key[1] is None:
        return None
    count = 0
    for node in nodes:
        if _field_key(node, parent_map) != target_key:
            continue
        count += 1
        if count == occurrence:
            return node.value
    return None
