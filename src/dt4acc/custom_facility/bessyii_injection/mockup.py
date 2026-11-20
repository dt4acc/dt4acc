"""Make a running injection twin behave as during injection: fire shots

A client of the twin, not part of it: the twin injects one shot per
``INJ:trigger``, as the machine does per injection timing event. What the
injection timing does at the machine (one shot after the other, at a
repetition rate, e.g. while filling or at top up) is done here, over EPICS
(PV Access), so it runs anywhere the twin's PVs are reachable.

    from dt4acc.custom_facility.bessyii_injection.mockup import InjectionMockup

    inj = InjectionMockup(prefix="BI")
    inj.shot()                       # one shot, returns when it is computed
    inj.shots(10, rate=1.0)          # 10 shots at 1 Hz

or from a shell (console script ``dt4acc_bessyii_injection_mockup``):

    DT4ACC_PREFIX=BI dt4acc_bessyii_injection_mockup --shots 10 --rate 1

Each shot waits until the twin has computed it (``INJ:count`` moved on), so
no trigger is merged into another. A rate faster than the twin can compute
is reported, the shots then follow as fast as the twin allows.
"""
import argparse
import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger("dt4acc-bessyii-injection")


class InjectionMockup:
    """Fires shots of a running injection twin (``<prefix>:INJ:trigger``)

    ``ctx``: a p4p client context (``p4p.client.thread.Context("pva",
    nt=False)``), made if not given.
    """

    def __init__(self, prefix: str = "", *, ctx=None, timeout: float = 30.0, poll: float = 0.05):
        if ctx is None:
            from p4p.client.thread import Context

            ctx = Context("pva", nt=False)
        self.prefix = prefix
        self.ctx = ctx
        self.timeout = timeout
        self.poll = poll

    def pv(self, name: str) -> str:
        return f"{self.prefix}:{name}" if self.prefix else name

    def count(self) -> int:
        """shots the twin has computed (``INJ:count``)"""
        value = self.ctx.get(self.pv("INJ:count"), timeout=5)
        return int(getattr(value, "value", value))

    def shot(self) -> int:
        """Fire one shot, wait until it is computed: the new ``INJ:count``

        TimeoutError if the twin does not compute it within ``timeout``.
        """
        before = self.count()
        self.ctx.put(self.pv("INJ:trigger"), 1)
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.timeout:
            n = self.count()
            if n > before:
                return n
            time.sleep(self.poll)
        raise TimeoutError(f"shot after INJ:count {before} not computed within {self.timeout} s")

    def shots(
        self, n: Optional[int] = None, *, rate: Optional[float] = None,
        after_each: Optional[Callable[[int], None]] = None,
    ) -> int:
        """Fire ``n`` shots (None: until interrupted), at ``rate`` [Hz] (None:
        each as soon as the previous one is computed); ``after_each(count)``
        after each one. Returns the last ``INJ:count``."""
        period = 1.0 / rate if rate else 0.0
        count, k = self.count(), 0
        while n is None or k < n:
            t0 = time.monotonic()
            count = self.shot()
            k += 1
            if after_each is not None:
                after_each(count)
            spent = time.monotonic() - t0
            if spent > period > 0.0:
                logger.warning("shot %d took %.2f s, longer than the period %.2f s (%.2f Hz)",
                               count, spent, period, rate)
            elif period > 0.0 and (n is None or k < n):
                time.sleep(period - spent)
        return count


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prefix", default=os.environ.get("DT4ACC_PREFIX", ""), help="the twin's prefix (DT4ACC_PREFIX)")
    p.add_argument("--shots", type=int, default=1, help="number of shots, 0: until interrupted (default: 1)")
    p.add_argument("--rate", type=float, default=None, help="repetition rate [Hz] (default: as fast as the twin computes)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    inj = InjectionMockup(prefix=a.prefix)
    try:
        inj.shots(a.shots or None, rate=a.rate, after_each=lambda count: print(f"INJ:count {count}", flush=True))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
