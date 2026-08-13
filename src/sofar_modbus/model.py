"""The component bases the two protocol generations build on."""

from __future__ import annotations

from dataclasses import dataclass

from modbus_connection import ModbusError
from modbus_connection.model import Component

from .variants import InverterType


class SofarComponentBase(Component):
    """A Sofar sub-system, tagged with the inverters it applies to.

    ``applies_to`` is the upstream ``allowedtypes`` mask of every entity in the
    component: components are cut along mask boundaries, so one component is
    either wholly served by an inverter or not read at all. A device polls the
    matching ones — see :func:`sofar_modbus.variants.matches`.
    """

    applies_to: InverterType = InverterType(0)


class SofarComponent(SofarComponentBase):
    """A sub-system of the current-generation (HYD / KTL-X) register map."""

    max_span = 48  # the plugin's block_size for this generation


class SofarLegacyComponent(SofarComponentBase):
    """A sub-system of the older register map."""

    max_span = 100  # the plugin's block_size for this generation


@dataclass(frozen=True)
class UpdateReport:
    """What one poll refreshed.

    A failed component kept its previous values and did not notify; the error
    that failed it rides along. A dead link is never in here — the update
    raises ``ModbusConnectionError`` instead of reporting partial silence.
    """

    updated: tuple[SofarComponentBase, ...]
    failed: tuple[tuple[SofarComponentBase, ModbusError], ...]

    @property
    def complete(self) -> bool:
        """Whether every polled component refreshed."""
        return not self.failed
