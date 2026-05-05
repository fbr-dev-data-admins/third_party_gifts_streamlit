"""Name parsing utilities."""


def parse_full_name(full_name: str) -> tuple[str, str, str]:
    """
    Parse a full name string into first, middle, and last name components.

    Args:
        full_name: Full name string to parse

    Returns:
        Tuple of (first_name, middle_name, last_name) in Proper Case

    Rules:
        - Split on spaces
        - first = first token
        - If second token is a single letter or letter + period:
          middle = that token (strip period), last = remaining tokens joined
        - Otherwise: middle = "", last = remaining tokens joined
        - If only one token: first = token, middle = "", last = ""
        - All outputs are Proper Case (title case)
    """
    if not full_name or not isinstance(full_name, str):
        return ("", "", "")

    parts = full_name.strip().split()

    if not parts:
        return ("", "", "")

    if len(parts) == 1:
        return (parts[0].title(), "", "")

    first = parts[0]

    if len(parts) == 2:
        return (first.title(), "", parts[1].title())

    second = parts[1].rstrip(".")
    if len(second) == 1 and second.isalpha():
        middle = second
        last = " ".join(parts[2:])
    else:
        middle = ""
        last = " ".join(parts[1:])

    return (first.title(), middle.title(), last.title())
