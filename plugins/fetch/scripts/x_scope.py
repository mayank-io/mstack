"""Reply-TARGET-aware scope filter. See design §7.1 — never filter on
reply-ness, only on reply target, or thread bodies vanish."""

_KEPT = {"original", "self_reply", "quote"}

def classify(post: dict, account_handle: str) -> str:
    if post.get("is_repost"):
        return "repost"
    reply = post.get("in_reply_to")
    if reply is not None:
        if reply.lower() == account_handle.lower():
            return "self_reply"
        return "reply_to_other"
    if post.get("has_quoted_status"):
        return "quote"
    return "original"

def is_kept(classification: str) -> bool:
    return classification in _KEPT
