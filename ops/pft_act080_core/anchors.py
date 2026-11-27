"""D-only source-backed Key K detectors on consecutive observed stock bars."""

from collections import deque


ANCHOR_TAGS = ("BREAKOUT", "REVERSAL", "VIOLENT", "FUNDING_ACTIVITY")


def _ratio(numerator, denominator):
    return numerator / denominator if denominator is not None and denominator > 0 else None


class KeyKDetector:
    def __init__(self):
        self.history = deque(maxlen=24)
        self.prior_breakout_predicates = deque(maxlen=7)

    def advance(self, bar):
        history = tuple(self.history)
        self.history.append(bar)
        previous = history[-1] if history else None
        percent = None
        volume_ratio = None
        breakout_predicate = None
        reversal = violent = funding = False
        if bar.positive_ohlc and previous is not None:
            relative_close = _ratio(bar.close, previous.close)
            percent = None if relative_close is None else 100 * (relative_close - 1)
            volume_ratio = _ratio(bar.volume, previous.volume)
            breakout_predicate = self._breakout_predicate(bar, history, percent)
            reversal = self._reversal(bar, history, percent)
            violent, funding = self._funding(bar, history, percent, volume_ratio)
        prior_flags = self.prior_breakout_predicates
        breakout = (
            breakout_predicate is True and len(prior_flags) == 7 and all(flag is False for flag in prior_flags)
        )
        prior_flags.append(breakout_predicate)
        return tuple(
            tag for tag, hit in zip(ANCHOR_TAGS, (breakout, reversal, violent, funding), strict=True) if hit
        )

    @staticmethod
    def _breakout_predicate(bar, history, percent):
        if len(history) < 20 or percent is None:
            return None
        highs = [prior.high for prior in history[-20:]]
        if min(highs) <= 0:
            return None
        return bar.close > max(highs) and bar.volume > 0.8 * history[-1].volume and percent > 4

    @staticmethod
    def _reversal(bar, history, percent):
        if len(history) < 24 or percent is None or percent <= 3:
            return False
        prior_ma24 = sum(prior.close for prior in history) / 24
        ma24 = (sum(prior.close for prior in history[1:]) + bar.close) / 24
        prior_mean_volume = sum(prior.volume for prior in history[-5:]) / 5
        return (
            bar.close > ma24 and history[-1].close <= prior_ma24
            and prior_mean_volume > 0 and bar.volume > 1.2 * prior_mean_volume
        )

    @staticmethod
    def _funding(bar, history, percent, volume_ratio):
        volumes = [prior.volume for prior in history[-4:]] + [bar.volume]
        mean_volume_ratio = _ratio(bar.volume, sum(volumes) / len(volumes))
        violent = (
            percent is not None and percent >= 4 and bar.close > bar.open
            and (
                (volume_ratio is not None and volume_ratio >= 1.5)
                or (mean_volume_ratio is not None and mean_volume_ratio >= 1.5)
            )
        )
        closes = [prior.close for prior in history] + [bar.close]
        bbi = sum(sum(closes[-size:]) / min(size, len(closes)) for size in (3, 6, 12, 24)) / 4
        volume_stand = volume_ratio is not None and volume_ratio >= 1.7 and bar.close >= bar.open and bar.close >= bbi
        return violent, violent or volume_stand
