import threading
import time

from services.common.memo import Memo


def test_get_caches_per_key_and_expires():
    memo, calls = Memo(ttl=0.05), []
    compute = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert memo.get("a", compute) == 1 and memo.get("a", compute) == 1
    time.sleep(0.06)
    assert memo.get("a", compute) == 2


def test_serve_returns_stale_value_and_refreshes_in_background():
    memo, done = Memo(), threading.Event()
    assert memo.serve("k", 1, lambda: "v1") == "v1"

    def slow():
        done.wait(1)
        return "v2"

    assert memo.serve("k", 2, slow) == "v1"  # version changed: stale value at once
    done.set()
    for _ in range(100):
        if memo.serve("k", 2, slow) == "v2":
            break
        time.sleep(0.01)
    assert memo.serve("k", 2, slow) == "v2"
    assert memo.refresh("k", 3, lambda: "v3") == "v3"
