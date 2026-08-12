"""Option maps the plugin declares, as enums."""

from __future__ import annotations

from enum import IntEnum


class PvRunMode(IntEnum):
    """Run Mode."""

    WAITING = 0
    CHECKING = 1
    NORMAL_MODE = 2
    FAULT = 3
    PERMANENT_FAULT_MODE = 4


class StorageRunMode(IntEnum):
    """Run Mode."""

    WAITING = 0
    CHECKING = 1
    NORMAL_MODE = 2
    CHECKING_DISCHARGE = 3
    DISCHARGE_MODE = 4
    EPS_MODE = 5
    FAULT = 6
    PERMANENT_FAULT_MODE = 7
