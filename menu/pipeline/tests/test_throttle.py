"""One rate budget, shared by every caller of a hosted model.

The bug this replaces is three independent sleep loops racing one free tier:
`generate_item_images` backed off on its own clock while a Celery task and a
management command each did the same, so the tier saw three callers and the
retry budget was spent three times over.

Redis and the clock are both injected -- no test here talks to a broker or
sleeps for real.
"""
import pytest

from menu.pipeline import throttle


class FakeRedis:
    """The four sorted-set operations the bucket uses, over a dict.

    Real Redis is a service, not a library: a test that needs one is an
    integration test that fails in CI for reasons that have nothing to do with
    the bucket's arithmetic.
    """

    def __init__(self):
        self.sets = {}

    def zremrangebyscore(self, key, lo, hi):
        kept = [s for s in self.sets.get(key, []) if not lo <= s <= hi]
        dropped = len(self.sets.get(key, [])) - len(kept)
        self.sets[key] = kept
        return dropped

    def zcard(self, key):
        return len(self.sets.get(key, []))

    def zadd(self, key, mapping):
        self.sets.setdefault(key, []).extend(mapping.values())
        self.sets[key].sort()
        return len(mapping)

    def zrange(self, key, start, end, withscores=False):
        scores = self.sets.get(key, [])[start:end + 1 or None]
        if withscores:
            return [(f'call-{s}'.encode(), s) for s in scores]
        return [f'call-{s}'.encode() for s in scores]

    def expire(self, key, seconds):
        return True


@pytest.fixture
def budgets(settings):
    """Explicit budgets, so these assertions do not move when production
    rate limits are retuned."""
    settings.NVIDIA_RATE_LIMITS = {
        'default': {'rpm': 40, 'min_interval': 0.0},
        'paced': {'rpm': 100, 'min_interval': 10.0},
        'small': {'rpm': 6, 'min_interval': 0.0},
    }
    return settings


def test_a_model_with_no_entry_gets_the_default_budget():
    b = throttle.budget_for('some/unlisted-model')
    assert b.rpm > 0


def test_image_generation_keeps_its_ten_second_pacing():
    """Its pacing is not a guess -- it is what the endpoint tolerated across
    four venues of generation."""
    from django.conf import settings
    assert throttle.budget_for(settings.NVIDIA_IMAGE_MODEL).min_interval == 10.0


def test_an_empty_bucket_does_not_wait():
    assert throttle.wait_time('m', client=FakeRedis(), now=1000.0) == 0


def test_the_minimum_interval_is_enforced_between_two_calls(budgets):
    client = FakeRedis()
    throttle.acquire('paced', client=client, now=1000.0, sleep=lambda s: None)
    # 4 s later, against a 10 s floor, the caller still owes 6 s.
    assert throttle.wait_time('paced', client=client, now=1004.0) == pytest.approx(6.0)


def test_a_full_window_waits_for_the_oldest_call_to_age_out(budgets):
    """The window is sliding, not fixed: after 6 calls at t=1000 the 7th is
    clear at t=1060, not at the top of the next minute. A fixed window would
    let 6 calls at :59 and 6 more at :01 pass as legal."""
    client = FakeRedis()
    for i in range(6):
        throttle.acquire('small', client=client, now=1000.0 + i,
                         sleep=lambda s: None)
    # The bucket is full (6 of 6); the oldest call (t=1000) ages out at t=1060.
    assert throttle.wait_time('small', client=client, now=1006.0) == pytest.approx(54.0)


def test_acquire_sleeps_exactly_what_it_owes_then_records_the_call(budgets):
    """A clear bucket does not sleep at all; the second call owes the remainder
    of the floor."""
    client, slept = FakeRedis(), []
    throttle.acquire('paced', client=client, now=1000.0, sleep=slept.append)
    throttle.acquire('paced', client=client, now=1002.0, sleep=slept.append)
    assert slept == [pytest.approx(8.0)]
    assert client.zcard('throttle:paced') == 2


def test_the_recorded_time_includes_the_wait_not_the_moment_it_started(budgets):
    """Recording the pre-sleep timestamp would let the next caller compute its
    floor from a call that had not happened yet."""
    client = FakeRedis()
    throttle.acquire('paced', client=client, now=1000.0, sleep=lambda s: None)
    throttle.acquire('paced', client=client, now=1002.0, sleep=lambda s: None)
    # The second call is stamped 1010 (1002 + the 8 s it waited), so at 1010 the
    # floor has only just started. Stamped 1002, this would read 2.0.
    assert throttle.wait_time('paced', client=client, now=1010.0) == pytest.approx(10.0)


def test_a_call_older_than_the_window_is_forgotten(budgets):
    client = FakeRedis()
    throttle.acquire('small', client=client, now=1000.0, sleep=lambda s: None)
    throttle.wait_time('small', client=client, now=1100.0)
    assert client.zcard('throttle:small') == 0


def test_backoff_doubles_and_starts_at_the_base():
    assert throttle.backoff_seconds(0, base=30) == 30
    assert throttle.backoff_seconds(1, base=30) == 60
    assert throttle.backoff_seconds(2, base=30) == 120


def test_backoff_is_capped_so_a_retry_loop_cannot_park_for_an_hour():
    assert throttle.backoff_seconds(12, base=30) <= throttle.MAX_BACKOFF
