"""Validation shared by source archives and REST payloads."""
import math


def validate_json_numbers(value):
    """Reject non-finite floats anywhere in nested JSON, including unknown source fields."""
    pending = [value]
    visited = set()
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON numbers must be finite")
        if isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            pending.extend(item.values() if isinstance(item, dict) else item)
    return value


def validate_source_metadata(value):
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    if "node_message_ids" in value:
        mapping = value["node_message_ids"]
        if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in mapping.items()):
            raise ValueError("metadata.node_message_ids must map strings to strings")
    if "non_text_blocks" in value:
        count = value["non_text_blocks"]
        if type(count) is not int or count < 0:
            raise ValueError("metadata.non_text_blocks must be a nonnegative integer")
    return value
