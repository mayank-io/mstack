"""Snowflake status-ID math. The one place SNOWFLAKE_EPOCH_MS lives."""

SNOWFLAKE_EPOCH_MS = 1288834974657
THREAD_GAP_MS = 1_800_000  # 30 min; see design §7.4 smoke investigation

def timestamp_ms(status_id: str) -> int:
    return (int(status_id) >> 22) + SNOWFLAKE_EPOCH_MS

def id_sort_key(status_id: str):
    return (len(status_id), status_id)

def same_thread(prev_id: str, next_id: str) -> bool:
    return timestamp_ms(next_id) - timestamp_ms(prev_id) <= THREAD_GAP_MS
