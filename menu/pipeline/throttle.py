"""One rate budget per model ID, shared by every caller.

Three independent sleep loops used to race the same free tier -- the image
command's `--backoff`, its per-image pacing, and whatever a Celery task did --
so the endpoint saw three callers while each believed it was alone. A sliding
window in Redis is the only version of this that works across a web process, a
worker and a CLI command at once.

The window is sliding rather than fixed: with a fixed window, six calls at
:59 and six more at :01 are twelve calls in two seconds and the tier says no.

Redis and the clock are injected so tests need neither.
"""
import time
import uuid
from typing import NamedTuple

WINDOW = 60.0
MAX_BACKOFF = 600.0


class Budget(NamedTuple):
    rpm: int
    min_interval: float


def _limits():
    from django.conf import settings
    return getattr(settings, 'NVIDIA_RATE_LIMITS', {}) or {}


def budget_for(model):
    """This model's budget, falling back to `default`.

    `rpm` is clamped to at least 1. A budget of 0 reads as "no calls allowed",
    which a function returning seconds-to-wait cannot express, and unclamped it
    made `wait_time` raise IndexError on an empty bucket instead: 0 calls
    satisfies `>= 0`, and there is then no oldest call to age out. One call per
    window is the strictest budget this module can actually honour, so a
    nonsense rpm lands there rather than on the caller's traceback.
    """
    limits = _limits()
    raw = limits.get(model) or limits.get('default') or {}
    return Budget(max(1, int(raw.get('rpm', 60))), float(raw.get('min_interval', 0.0)))


def _client():
    import redis
    from django.conf import settings
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def _key(model):
    return f'throttle:{model}'


def wait_time(model, *, client, now):
    """Seconds this caller must wait before calling `model`. 0 when clear.

    Also prunes calls that have aged out of the window, so the key cannot grow
    without bound for a model nobody has called in an hour.
    """
    budget, key = budget_for(model), _key(model)
    client.zremrangebyscore(key, 0, now - WINDOW)
    # `withscores` matters: the members are unique strings, and only the scores
    # are the timestamps. Reading members and calling float() on them is the
    # obvious-looking version that raises on the first real Redis call.
    recent = [score for _, score in client.zrange(key, 0, -1, withscores=True)]
    waits = [0.0]
    if budget.min_interval and recent:
        waits.append(budget.min_interval - (now - recent[-1]))
    if len(recent) >= budget.rpm:
        waits.append(WINDOW - (now - recent[0]))
    return max(waits)


def acquire(model, *, client=None, now=None, sleep=time.sleep):
    """Block until `model`'s budget allows one more call; record it.

    Returns the seconds waited, so a caller can report pacing without keeping
    its own clock.
    """
    client = _client() if client is None else client
    now = time.time() if now is None else now
    waited = wait_time(model, client=client, now=now)
    if waited > 0:
        sleep(waited)
        now += waited
    key = _key(model)
    # A unique member per call. `id(object())` looks unique and is not -- the
    # object is freed immediately and CPython recycles the address, so two calls
    # in the same second can collide, and a duplicate member UPDATES a sorted-set
    # entry rather than adding one. That under-counts the budget silently.
    client.zadd(key, {f'{now}:{uuid.uuid4().hex}': now})
    client.expire(key, int(WINDOW * 2))
    return waited


def backoff_seconds(attempt, *, base):
    """Doubling backoff, capped.

    Uncapped doubling parks a retry loop for an hour on the 7th attempt, which
    reads as a hung job rather than a rate limit.
    """
    return min(base * (2 ** attempt), MAX_BACKOFF)
