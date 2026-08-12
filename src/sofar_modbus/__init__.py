"""sofar-modbus — read Sofar Solar inverters over Modbus.

Two protocol generations live side by side, each with its own top-level device
object built on ``modbus_connection.model``::

    from modbus_connection import ModbusTcpParams
    from modbus_connection.tmodbus import ModbusConnection
    from sofar_modbus import SofarInverter

    connection = ModbusConnection(ModbusTcpParams(host="10.0.0.5", framer="rtu"))
    inverter = SofarInverter(connection.for_unit(1))
    await inverter.async_update()
    inverter.grid.active_power_output_total

- :class:`SofarInverter` — the current HYD / KTL-X generation.
- :class:`SofarLegacyInverter` — the older SA/SB/SC/SM1E generation.

Which registers an inverter serves depends on its model, encoded as an
:class:`InverterType` bitmask on every component. See :mod:`sofar_modbus.variants`.

ASCII framing over TCP is not supported: build the ``ModbusUnit`` from an RTU or
RTU-over-TCP connection.
"""

from .legacy import SofarLegacyInverter
from .model import SofarComponent, SofarComponentBase, SofarLegacyComponent
from .modern import SofarInverter
from .variants import InverterType, matches

__all__ = [
    "InverterType",
    "SofarComponent",
    "SofarComponentBase",
    "SofarInverter",
    "SofarLegacyComponent",
    "SofarLegacyInverter",
    "matches",
]
