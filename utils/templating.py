import re
from html import escape
from typing import Any

MERGE_FIELD = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*(?:\|\s*([^}]*?)\s*)?\}\}")

DEFAULT_UNSUBSCRIBE_TEXT = "Not interested? Reply with \"unsubscribe\" and we won't email you again."


def render_template(template: str, variables: dict[str, Any], html: bool = False, drop_empty_lines: bool = False) -> str:
    """Fill {{field}} / {{field|fallback}} merge fields from a contact row.

    Fields with no value and no fallback are left in place so the spam guard
    flags them as unfilled placeholders instead of sending a broken email.
    With drop_empty_lines, a line whose field is empty is removed instead —
    used by the built-in templates for optional lines like the resume link.
    """
    lookup = {str(key).strip().lower(): str(value).strip() for key, value in (variables or {}).items() if str(value).strip()}

    if drop_empty_lines:
        def line_is_unfillable(line: str) -> bool:
            return any(match.group(1).lower() not in lookup and match.group(2) is None for match in MERGE_FIELD.finditer(line))

        template = "\n".join(line for line in (template or "").split("\n") if not line_is_unfillable(line))
        template = re.sub(r"\n{3,}", "\n\n", template).strip()

    def replace(match: re.Match) -> str:
        value = lookup.get(match.group(1).lower())
        if value is None:
            value = match.group(2)
        if value is None:
            return match.group(0)
        return escape(value) if html else value

    rendered = MERGE_FIELD.sub(replace, template or "")
    if html and not re.search(r"<(p|div|br|ul|table)\b", rendered, re.IGNORECASE):
        paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", rendered) if chunk.strip()]
        rendered = "".join(f"<p>{chunk.replace(chr(10), '<br>')}</p>" for chunk in paragraphs)
    return rendered


def merge_fields(template: str) -> list[str]:
    return sorted({match.group(1).lower() for match in MERGE_FIELD.finditer(template or "")})


def with_compliance_footer(body: str, profile: dict[str, Any]) -> str:
    """Append the sender identity and opt-out line that bulk campaigns are expected to carry."""
    if "data-compliance-footer" in (body or ""):
        return body
    identity = " · ".join(
        escape(part) for part in (profile.get("organization"), profile.get("physical_address")) if part
    )
    unsubscribe = escape(profile.get("unsubscribe_text") or DEFAULT_UNSUBSCRIBE_TEXT)
    lines = [line for line in (identity, unsubscribe) if line]
    footer = (
        '<p data-compliance-footer style="margin-top:24px;font-size:12px;color:#6b7280;">'
        + "<br>".join(lines)
        + "</p>"
    )
    return f"{body or ''}{footer}"
