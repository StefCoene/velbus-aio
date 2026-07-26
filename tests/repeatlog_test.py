"""Test cases for RepeatCollapser, the repeated-log-line collapser."""

import logging

import pytest

from velbusaio.repeatlog import RepeatCollapser


@pytest.fixture(name="log")
def log_fixture():
    """Return a logger dedicated to one test."""
    return logging.getLogger("velbus-repeatlog-test")


def debug_lines(caplog):
    """Return the debug messages captured so far."""
    return [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]


def warnings(caplog):
    """Return the warning messages captured so far."""
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


class TestRepeatCollapser:
    """Test cases for RepeatCollapser."""

    def test_distinct_lines_pass_through(self, log, caplog):
        """Different lines are logged verbatim, one for one."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log)

        collapser.log("RX: a")
        collapser.log("RX: b")
        collapser.log("RX: c")

        assert debug_lines(caplog) == ["RX: a", "RX: b", "RX: c"]
        assert warnings(caplog) == []

    def test_repeats_are_collapsed(self, log, caplog):
        """A run of identical lines yields the first line plus one summary."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=1000, flush_seconds=1000)

        for _ in range(50):
            collapser.log("RX: same")
        collapser.log("RX: other")
        collapser.flush()

        lines = debug_lines(caplog)
        assert lines[0] == "RX: same"
        assert lines[1] == "RX: other"
        assert "RX: same [repeated 49 more times" in lines[2]
        assert len(lines) == 3

    def test_quiet_run_is_swept_out(self, log, caplog):
        """A run that stops repeating is reported on the next call, not held.

        flush_seconds=0 makes every call sweep, standing in for a real run whose
        reporting period has elapsed.
        """
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=1000, flush_seconds=0)

        collapser.log("RX: a")
        collapser.log("RX: a")
        collapser.log("RX: b")

        lines = debug_lines(caplog)
        assert lines[0] == "RX: a"
        assert "RX: a [repeated 1 more times" in lines[1]
        assert lines[2] == "RX: b"

    def test_interim_summary_on_count(self, log, caplog):
        """An ongoing run is summarised every flush_count repeats."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=10, flush_seconds=1000)

        for _ in range(31):
            collapser.log("RX: same")

        # First line, then a summary at every 10 repeats: 30 repeats -> 3.
        lines = debug_lines(caplog)
        assert lines[0] == "RX: same"
        assert sum("repeated 10 more times" in line for line in lines) == 3
        assert len(lines) == 4

    def test_flush_reports_a_pending_run(self, log, caplog):
        """flush() reports a run that has not ended yet."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=1000, flush_seconds=1000)

        collapser.log("RX: same")
        collapser.log("RX: same")
        collapser.log("RX: same")
        collapser.flush()

        assert "repeated 2 more times" in debug_lines(caplog)[-1]

    def test_flush_without_a_run_is_silent(self, log, caplog):
        """flush() emits nothing when there is no run pending."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=1000, flush_seconds=1000)

        collapser.log("RX: a")
        before = len(debug_lines(caplog))
        collapser.flush()

        assert len(debug_lines(caplog)) == before

    def test_storm_warns_once(self, log, caplog):
        """A sustained run warns, and only once per storm_warn_interval."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(
            log, flush_count=10, flush_seconds=1000, storm_rate=1.0
        )

        for _ in range(100):
            collapser.log("RX: 0f f8 07 04 00 10 00 00 de 04")

        got = warnings(caplog)
        assert len(got) == 1
        assert "Frame storm" in got[0]
        assert "0f f8 07 04 00 10 00 00 de 04" in got[0]

    def test_slow_repeats_do_not_warn(self, log, caplog):
        """Repeats below the storm rate are collapsed but never warn.

        A high storm_rate stands in for a slow real-world trickle: the run is
        summarised, but nothing about it is pathological.
        """
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(
            log, flush_count=5, flush_seconds=1000, storm_rate=1e9
        )

        for _ in range(20):
            collapser.log("RX: same")

        assert warnings(caplog) == []
        assert any("repeated" in line for line in debug_lines(caplog))

    def test_warning_fires_without_debug_logging(self, log, caplog):
        """The storm warning does not depend on debug logging being enabled.

        This is the point of the warning: a storm has to be visible in a default
        installation, without asking the user to turn on debug logging first.
        """
        caplog.set_level(logging.WARNING)
        collapser = RepeatCollapser(
            log, flush_count=10, flush_seconds=1000, storm_rate=1.0
        )

        for _ in range(50):
            collapser.log("RX: same")

        assert len(warnings(caplog)) == 1
        assert debug_lines(caplog) == []

    def test_percent_signs_are_not_format_specifiers(self, log, caplog):
        """A line containing % is logged literally, not treated as a template."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log)

        collapser.log("RX: 100% duty, %s %d %(oops)s")

        assert debug_lines(caplog) == ["RX: 100% duty, %s %d %(oops)s"]

    def test_interleaved_lines_still_collapse(self, log, caplog):
        """Repeats collapse even when they alternate rather than run together.

        This is the case that matters on the raw read path: a read size that does
        not divide the frame size makes a steady stream cycle through several
        phases, so the duplicates never land next to each other.
        """
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, flush_count=1000, flush_seconds=1000)

        for _ in range(100):
            collapser.log("RX: a")
            collapser.log("RX: b")
        collapser.flush()

        lines = debug_lines(caplog)
        assert lines[0] == "RX: a"
        assert lines[1] == "RX: b"
        assert "RX: a [repeated 99 more times" in lines[2]
        assert "RX: b [repeated 99 more times" in lines[3]
        assert len(lines) == 4

    def test_window_eviction_reports_pending_counts(self, log, caplog):
        """A line pushed out of the window still gets its summary."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, window=2, flush_count=1000, flush_seconds=1000)

        collapser.log("RX: a")
        collapser.log("RX: a")  # a: 1 repeat pending
        collapser.log("RX: b")
        collapser.log("RX: c")  # evicts a, which must report its repeat

        lines = debug_lines(caplog)
        assert "RX: a [repeated 1 more times" in " ".join(lines)
        assert lines[-1] == "RX: c"

    def test_varied_traffic_is_not_delayed(self, log, caplog):
        """Distinct lines are logged as they arrive, never held back."""
        caplog.set_level(logging.DEBUG)
        collapser = RepeatCollapser(log, window=4)

        for n in range(20):
            collapser.log(f"RX: {n}")

        assert debug_lines(caplog) == [f"RX: {n}" for n in range(20)]
