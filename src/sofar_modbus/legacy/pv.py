"""PV strings and PV-inverter output on the older register map."""

from __future__ import annotations

from modbus_connection.model import enum, gauge, integer, uint32

from ..model import SofarLegacyComponent
from ..variants import HYBRID, PV, X1, X3
from .enums import PvRunMode


class PvCommon(SofarLegacyComponent):
    """What the plugin reads on every PV inverter, single- or three-phase."""

    applies_to = PV

    run_mode = enum(0x0000, PvRunMode, signed=False)
    pv_voltage_1 = gauge(0x0006, 0.1, signed=False, unit="V")
    pv_current_1 = gauge(0x0007, 0.01, signed=False, unit="A")
    inverter_heatsink_temperature = integer(0x001B, signed=True, unit="°C")
    inverter_inner_temperature = integer(0x001C, signed=True, unit="°C")


class SinglePhasePv(SofarLegacyComponent):
    """A single-phase PV inverter's output and yield."""

    applies_to = X1 | PV

    pv_power = gauge(0x000A, 0.01, signed=False, unit="kW")
    activepower = gauge(0x000C, 0.01, signed=False, unit="kW")
    reactivepower = gauge(0x000D, 0.01, signed=True, unit="var")
    grid_frequency = gauge(0x000E, 0.01, signed=False, unit="Hz")
    voltage = gauge(0x000F, 0.1, signed=False, unit="V")
    current = gauge(0x0010, 0.01, signed=False, unit="A")
    total_production = uint32(0x0015, unit="kWh")
    total_time = uint32(0x0017, unit="h")
    today_production = gauge(0x0019, 0.01, signed=False, unit="kWh")
    today_time = integer(0x001A, signed=False, unit="min")


class ThreePhasePv(SofarLegacyComponent):
    """A three-phase PV inverter's strings, per-phase output and yield."""

    applies_to = X3 | PV

    pv_voltage_2 = gauge(0x0008, 0.1, signed=False, unit="V")
    pv_current_2 = gauge(0x0009, 0.01, signed=True, unit="A")
    pv_voltage_3 = gauge(0x000A, 0.1, signed=False, unit="V")
    pv_current_3 = gauge(0x000B, 0.01, signed=True, unit="A")
    pv_power_1 = gauge(0x000C, 0.01, signed=False, unit="W")
    pv_power_2 = gauge(0x000D, 0.01, signed=False, unit="W")
    pv_power_3 = gauge(0x000E, 0.01, signed=False, unit="W")
    activepower = gauge(0x000F, 0.01, signed=False, unit="kWh")
    reactivepower = gauge(0x0010, 0.01, signed=True, unit="var")
    grid_frequency = gauge(0x0011, 0.01, signed=False, unit="Hz")
    voltage_r = gauge(0x0012, 0.1, signed=False, unit="V")
    current_r = gauge(0x0014, 0.01, signed=False, unit="A")
    voltage_s = gauge(0x0014, 0.1, signed=False, unit="V")
    current_s = gauge(0x0015, 0.01, signed=False, unit="A")
    voltage_t = gauge(0x0016, 0.1, signed=False, unit="V")
    current_t = gauge(0x0017, 0.01, signed=False, unit="A")
    total_production = uint32(0x0018, unit="kWh")
    total_time = uint32(0x001A, unit="h")
    today_production = gauge(0x001C, 0.01, signed=False, unit="kWh")
    today_time = integer(0x001D, signed=False, unit="min")
    inverter_heatsink_temperature = integer(0x001E, signed=True, unit="°C")
    inverter_inner_temperature = integer(0x001F, signed=True, unit="°C")
    bus_voltage = gauge(0x0020, 0.1, signed=False, unit="V")


class HybridPvString1(SofarLegacyComponent):
    """PV string 1 of a hybrid inverter."""

    applies_to = HYBRID
    register_ranges = ((0x0250, 0x0252),)

    pv_oltage_1 = gauge(0x0250, 0.1, signed=False, unit="V")
    """PV Voltage 1."""
    pv_current_1 = gauge(0x0251, 0.01, signed=False, unit="A")
    pv_power_1 = gauge(0x0252, 10, signed=False, unit="W")


class HybridPvString2(SofarLegacyComponent):
    """PV string 2 of a hybrid inverter."""

    applies_to = HYBRID
    register_ranges = ((0x0253, 0x0255),)

    pv_oltage_2 = gauge(0x0253, 0.1, signed=False, unit="V")
    """PV Voltage 2."""
    pv_current_2 = gauge(0x0254, 0.01, signed=False, unit="A")
    pv_power_2 = gauge(0x0255, 10, signed=False, unit="W")
