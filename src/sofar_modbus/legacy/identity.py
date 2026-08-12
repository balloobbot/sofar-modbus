"""The serial number, which lives in the input-register space on this map."""

from __future__ import annotations

from modbus_connection.model import string

from ..model import SofarLegacyComponent
from ..variants import InverterType


class LegacyIdentity(SofarLegacyComponent):
    """The inverter's serial number."""

    applies_to = InverterType(0)
    register_space = "input"

    serial_number = string(0x2002, 6)
