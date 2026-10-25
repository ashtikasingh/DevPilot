import math
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable


DEFAULT_QA_RATE_LIMIT = 10
DEFAULT_QA_RATE_WINDOW_SECONDS = 60
MAX_QA_RATE_LIMIT = 60
MAX_QA_RATE_WINDOW_SECONDS = 60 * 60
MAX_TRACKED_CLIENTS = 2048
OVERFLOW_CLIENT_KEY = "\x00overflow"


def _bounded_environment_integer(name: str, default: int, maximum: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if 1 <= value <= maximum else default


def qa_rate_limit_settings() -> tuple[int, int]:
    return (
        _bounded_environment_integer(
            "GEMINI_QA_RATE_LIMIT", DEFAULT_QA_RATE_LIMIT, MAX_QA_RATE_LIMIT
        ),
        _bounded_environment_integer(
            "GEMINI_QA_RATE_WINDOW_SECONDS",
            DEFAULT_QA_RATE_WINDOW_SECONDS,
            MAX_QA_RATE_WINDOW_SECONDS,
        ),
    )


class InMemorySlidingWindowLimiter:
    """Bounded, process-local per-client sliding-window limiter."""

    def __init__(
        self,
        max_clients: int = MAX_TRACKED_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_clients = max_clients
        self._clock = clock
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, client_key: str, limit: int, window_seconds: int) -> int | None:
        """Return retry-after seconds when over limit, otherwise record and allow."""
        now = self._clock()
        with self._lock:
            requests = self._requests.get(client_key)
            if requests is None and len(self._requests) >= self._max_clients:
                client_key = OVERFLOW_CLIENT_KEY
                requests = self._requests.get(client_key)
                if requests is None:
                    self._requests.popitem(last=False)
                    requests = deque()
                    self._requests[client_key] = requests

            if requests is not None:
                cutoff = now - window_seconds
                while requests and requests[0] <= cutoff:
                    requests.popleft()
                self._requests.move_to_end(client_key)
                if not requests:
                    del self._requests[client_key]
                    requests = None

            if requests is not None and len(requests) >= limit:
                retry_after = math.ceil(window_seconds - (now - requests[0]))
                return max(1, retry_after)

            if requests is None:
                requests = deque()
                self._requests[client_key] = requests

            requests.append(now)
            self._requests.move_to_end(client_key)
            return None

    def clear(self) -> None:
        """Clear state, primarily to isolate tests and application lifecycle resets."""
        with self._lock:
            self._requests.clear()


qa_request_limiter = InMemorySlidingWindowLimiter()

# Decision writes have their own process-local bucket so this feature does not
# consume or alter the existing Gemini Q&A allowance.
DECISION_WRITE_RATE_LIMIT = 10
DECISION_WRITE_RATE_WINDOW_SECONDS = 60
decision_write_limiter = InMemorySlidingWindowLimiter()
