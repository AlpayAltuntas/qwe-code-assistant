"""XML-specific half of the mapping engine's source support: converts a
parsed UBL or CII document into the unified IR (see ir.py) that all the
generic field-addressing/extraction logic runs against.

Line-item repetition is real subtree nesting for these formats — every
occurrence of the format's line-item container element (cac:InvoiceLine
for UBL, ram:IncludedSupplyChainTradeLineItem for CII) anywhere in the
tree is one line-item group. ir.build_scope's generic containment check
handles the rest; this module's only job is turning an ElementTree tree
into an ir.Node tree with the right tags and leaf values.
"""

from mcp_server.ir import Node

LINE_CONTAINER_LOCAL_TAG = {
    "ubl": "InvoiceLine",
    "cii": "IncludedSupplyChainTradeLineItem",
}


def local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def to_ir(root) -> Node:
    """Converts an ElementTree element into an ir.Node — near 1:1, since
    XML is already properly nested. A leaf's `value` is its stripped
    direct text (None if empty, matching the "only text-bearing leaves"
    scope parse_edi's element walker already uses for UBL/CII)."""
    text = (root.text or "").strip()
    node = Node(tag=local_name(root.tag), value=text or None)
    for child in root:
        node.children.append(to_ir(child))
    return node
