"""Offline thread clustering over the manifest. See design §7.4."""
from x_snowflake import id_sort_key, same_thread

def cluster(posts: list) -> list:
    ordered = sorted(posts, key=lambda p: id_sort_key(p["status_id"]))
    clusters, cur = [], []
    for p in ordered:
        sid = p["status_id"]
        if not cur:
            cur = [sid]
            continue
        joins = (not p.get("is_reply_to_other")) and same_thread(cur[-1], sid)
        if joins:
            cur.append(sid)
        else:
            clusters.append(cur)
            cur = [sid]
    if cur:
        clusters.append(cur)
    return clusters
