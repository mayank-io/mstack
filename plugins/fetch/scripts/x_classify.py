"""Adaptive click-through classification (pure). See design §7.2.

A post is harvested from the timeline node directly UNLESS one of its own
post-specific signals requires opening the full post view. Critically,
approximate metrics do NOT force a click-in — only include_metrics == "exact"
does. A trigger that is true by default would silently turn the adaptive
strategy into 'always' (design §7.2 hazard)."""

def needs_click_in(node_signals: dict, include_metrics: str) -> bool:
    if node_signals.get("is_thread"):
        return True
    if node_signals.get("truncated"):
        return True
    if node_signals.get("is_article"):
        return True
    if node_signals.get("photo_count", 0) > 0:
        return True
    if include_metrics == "exact":
        return True
    return False
