"""Pure parsing and allocation rules for stable, readable work item IDs."""

import re


ALPHABET = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_ID_LENGTH = 128
SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
HIERARCHICAL_ID = re.compile(r"([1-9A-Z]+)-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\Z")


def parse_id(identifier):
    """Return (hierarchy code, slug), or None for a legacy opaque ID."""
    if not isinstance(identifier, str) or len(identifier) > MAX_ID_LENGTH:
        return None
    match = HIERARCHICAL_ID.fullmatch(identifier)
    return match.groups() if match else None


def hierarchy_errors(items):
    """Check hierarchy references independently of the dependency DAG."""
    errors, by_code = [], {}
    for identifier in items:
        parsed = parse_id(identifier)
        if parsed is None:
            continue
        code, _ = parsed
        if code in by_code:
            errors.append(f"duplicate hierarchy code {code}: {by_code[code]}, {identifier}")
        else:
            by_code[code] = identifier
    for identifier, item in items.items():
        parsed = parse_id(identifier)
        if parsed is None:
            continue
        code, _ = parsed
        if len(code) == 1:
            if item.get("split_from") is not None:
                errors.append(f"item {identifier}: hierarchy root split_from must be null")
        else:
            parent = by_code.get(code[:-1])
            if parent is None:
                errors.append(f"item {identifier}: missing hierarchy parent code {code[:-1]}")
            elif item.get("split_from") != parent:
                errors.append(f"item {identifier}: split_from must be full hierarchy parent id {parent}")
    return errors


def allocate_ids(items, slugs, parent=None):
    """Return an entire candidate batch without reserving or mutating metadata."""
    slugs = list(slugs)
    if not slugs:
        raise ValueError("at least one slug is required")
    for slug in slugs:
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError(f"invalid slug {slug!r}: use lowercase ASCII words separated by single hyphens, starting with a letter")
    prefix = ""
    if parent is not None:
        if parent not in items:
            raise ValueError(f"unknown parent work item (full canonical id required): {parent}")
        parsed = parse_id(parent)
        if parsed is None:
            raise ValueError(f"parent {parent} has no hierarchy code; explicitly migrate its identity before allocating children")
        prefix = parsed[0]
    errors = hierarchy_errors(items)
    if errors:
        raise ValueError("invalid work item hierarchy:\n" + "\n".join(errors))
    highest = -1
    for identifier in items:
        parsed = parse_id(identifier)
        if parsed is not None:
            code, _ = parsed
            if len(code) == len(prefix) + 1 and code.startswith(prefix):
                highest = max(highest, ALPHABET.index(code[-1]))
    # known-limit: one character per layer allows 35 siblings. More siblings
    # require changing the numbering contract, never multi-character ordinals.
    if highest + len(slugs) >= len(ALPHABET):
        raise ValueError(f"hierarchy level {prefix or '<root>'} exceeds the 35-item limit; batch was not allocated")
    candidates = [f"{prefix}{ALPHABET[highest + offset + 1]}-{slug}"
                  for offset, slug in enumerate(slugs)]
    if any(len(identifier) > MAX_ID_LENGTH for identifier in candidates):
        raise ValueError("work item id must be at most 128 characters; batch was not allocated")
    return candidates
