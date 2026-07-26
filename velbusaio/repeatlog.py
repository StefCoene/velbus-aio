"""Collapse repeated log lines.

One misbehaving module -- or a gateway that duplicates frames -- can repeat a
single Velbus frame hundreds of times per second. Logging every copy buries
everything else: a reported case produced two 1.8 MB debug logs that between
them contained exactly one unique message and not a single transmitted frame,
which kept the actual fault invisible for months.

RepeatCollapser logs the first occurrence of a line, counts the copies that
follow, and emits one summary line instead of thousands. A run that keeps going
is summarised periodically so a live log never falls silent, and a sustained run
is additionally reported at WARNING level. That warning is the point of the whole
thing: it fires irrespective of the debug level, so a frame storm becomes visible
without asking anyone to enable debug logging first.

Why a window instead of plain run-length collapsing: on the raw read path the
line contains whatever the transport handed over, and a read size that does not
divide the frame size makes a perfectly steady stream cycle through several
phases. Replaying the reported flood produced 2976 read lines with only 6 unique
values, none of them consecutive -- collapsing only the immediately preceding
line would have suppressed nothing at all. So counts are tracked for the last
`window` distinct lines, and any of them collapses no matter how they interleave.

Identity is the log line itself, so a caller only has to route its existing
message through log() instead of straight to logger.debug().
"""

from __future__ import annotations

from collections import OrderedDict
import logging
import time

# Emit an interim summary after this many repeats, or this many seconds,
# whichever comes first. Together they bound how much a storm can grow the log
# while keeping a live log visibly ticking over.
FLUSH_COUNT: int = 250
FLUSH_SECONDS: float = 5.0

# How many distinct recent lines to keep counts for. Large enough to cover the
# handful of phases a rotating read pattern produces, small enough that ordinary
# varied traffic pushes entries out quickly and is logged as it happens.
WINDOW: int = 8

# A line arriving at or above this rate is a storm, not a busy bus: a healthy
# Velbus at 16.6 kbit/s carries well under 200 frames/s in total, so 25 copies
# per second of one single line is already pathological.
STORM_RATE: float = 25.0

# Do not repeat the warning more often than this, so a storm lasting hours
# does not itself become the flood it reports.
STORM_WARN_INTERVAL: float = 300.0


class RepeatCollapser:
    """Collapse repeated log lines into periodic summaries."""

    def __init__(
        self,
        log: logging.Logger,
        *,
        window: int = WINDOW,
        flush_count: int = FLUSH_COUNT,
        flush_seconds: float = FLUSH_SECONDS,
        storm_rate: float = STORM_RATE,
        storm_warn_interval: float = STORM_WARN_INTERVAL,
    ) -> None:
        """Initialize the collapser for one logger."""
        self._log = log
        self._window = max(window, 1)
        self._flush_count = flush_count
        self._flush_seconds = flush_seconds
        self._storm_rate = storm_rate
        self._storm_warn_interval = storm_warn_interval

        # line -> [repeat count since the last summary, when that period began].
        # Ordered by recency, so the least recently seen line is evicted first.
        self._runs: OrderedDict[str, list[float]] = OrderedDict()
        self._warned_at: float | None = None

    def log(self, text: str) -> None:
        """Log text at debug level, collapsing it if it has been seen recently."""
        now = time.monotonic()
        # Report runs that have gone quiet. Without this a storm that stops --
        # or a line that simply never recurs -- would keep its pending count
        # until the next flush(), which may be hours away. The window holds at
        # most `window` entries, so this stays cheap.
        self._sweep(now)

        run = self._runs.get(text)
        if run is not None:
            run[0] += 1
            self._runs.move_to_end(text)
            if run[0] >= self._flush_count or now - run[1] >= self._flush_seconds:
                self._summarise(text, now)
            return

        # New line: make room for it, reporting whatever the evicted line still
        # has pending so no count is silently dropped.
        while len(self._runs) >= self._window:
            oldest = next(iter(self._runs))
            self._summarise(oldest, now, evict=True)

        self._runs[text] = [0, now]
        # text is passed as the whole message rather than as a format string:
        # it is caller-formatted and may legitimately contain % characters.
        self._log.debug(text)

    def _sweep(self, now: float) -> None:
        """Summarise runs whose reporting period has elapsed."""
        for text in list(self._runs):
            run = self._runs[text]
            if run[0] and now - run[1] >= self._flush_seconds:
                self._summarise(text, now)

    def flush(self) -> None:
        """Report every pending run, e.g. when the connection goes down."""
        now = time.monotonic()
        for text in list(self._runs):
            self._summarise(text, now, evict=True)

    def _summarise(self, text: str, now: float, *, evict: bool = False) -> None:
        """Emit the summary for one line's accumulated repeats."""
        run = self._runs[text]
        count = int(run[0])

        if count:
            # A run is only summarised after at least one repeat, so elapsed is
            # positive in practice; clamp anyway so the rate stays finite.
            elapsed = max(now - run[1], 1e-9)
            self._log.debug(
                "%s [repeated %d more times in %.1f s]", text, count, elapsed
            )
            self._maybe_warn(text, count, elapsed, now)

        if evict:
            del self._runs[text]
        else:
            run[0] = 0
            run[1] = now

    def _maybe_warn(self, text: str, count: int, elapsed: float, now: float) -> None:
        """Report a sustained run at WARNING level, at most once per interval."""
        rate = count / elapsed
        if rate < self._storm_rate:
            return
        if (
            self._warned_at is not None
            and now - self._warned_at < self._storm_warn_interval
        ):
            return
        self._warned_at = now
        self._log.warning(
            "Frame storm: the same message arrived %d times in %.1f s (%.0f/s): %s. "
            "One module or gateway is repeating a single frame and is crowding out "
            "the rest of the bus traffic.",
            count,
            elapsed,
            rate,
            text,
        )
