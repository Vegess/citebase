"""In-process counters for GET /metrics.

The one that matters most is `fallback_total`: it counts answers produced by
the degraded local fallback instead of the LLM. During the Groq outage every
answer was a fallback while uptime, error rate and latency all looked healthy;
this counter is the signal that would have caught it.

Counters reset when the process restarts. `started_at` and `commit` let a
reader (Vigil) tell a reset or a deploy apart from a real drop.
"""
import time
from collections import Counter, deque
from threading import Lock

_lock = Lock()
_started = time.time()
_requests_total = 0
_requests_by_status: Counter = Counter()
_latencies_ms: deque[int] = deque(maxlen=1000)
_chat_times: deque[float] = deque(maxlen=5000)
_fallback_times: deque[float] = deque(maxlen=5000)
_fallback_total = 0
_fallback_reasons: Counter = Counter()
_empty_retrievals = 0
_chat_total = 0


def record_request(status_code: int, latency_ms: int) -> None:
    global _requests_total
    with _lock:
        _requests_total += 1
        _requests_by_status[str(status_code)] += 1
        _latencies_ms.append(latency_ms)


def record_chat(retrieved_chunks: int) -> None:
    global _chat_total, _empty_retrievals
    with _lock:
        _chat_total += 1
        _chat_times.append(time.time())
        if retrieved_chunks == 0:
            _empty_retrievals += 1


def record_fallback(reason: str) -> None:
    global _fallback_total
    with _lock:
        _fallback_total += 1
        _fallback_reasons[reason] += 1
        _fallback_times.append(time.time())


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


def snapshot() -> dict:
    now = time.time()
    window = now - 300
    with _lock:
        latencies = list(_latencies_ms)
        chats_5m = sum(1 for t in _chat_times if t >= window)
        fallbacks_5m = sum(1 for t in _fallback_times if t >= window)
        return {
            "uptime_s": int(now - _started),
            "requests_total": _requests_total,
            "requests_by_status": dict(_requests_by_status),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "chat_requests_total": _chat_total,
            "chat_requests_5m": chats_5m,
            "empty_retrievals_total": _empty_retrievals,
            "fallback_total": _fallback_total,
            "fallback_reasons": dict(_fallback_reasons),
            "fallback_5m": fallbacks_5m,
            "fallback_rate_5m": round(fallbacks_5m / chats_5m, 3) if chats_5m else 0.0,
        }
