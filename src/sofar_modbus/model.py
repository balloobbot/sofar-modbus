"""The component bases the two protocol generations build on."""

from __future__ import annotations

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
