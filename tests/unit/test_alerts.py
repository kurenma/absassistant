from datetime import date
from unittest.mock import Mock

import pytest

from services.alerts import list_alerts


@pytest.mark.parametrize(
    ("expiry_warning_days", "inactivity_days", "message"),
    [
        (0, 30, "expiry_warning_days must be positive"),
        (30, 0, "inactivity_days must be positive"),
    ],
)
def test_list_alerts_rejects_nonpositive_thresholds(
    expiry_warning_days,
    inactivity_days,
    message,
):
    with pytest.raises(ValueError, match=message):
        list_alerts(
            Mock(),
            date(2026, 9, 15),
            expiry_warning_days=expiry_warning_days,
            inactivity_days=inactivity_days,
        )
