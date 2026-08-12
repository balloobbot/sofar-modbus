"""Storage/hybrid inverter registers on the older register map."""

from __future__ import annotations

from modbus_connection.model import enum, gauge, integer, uint32

from ..model import SofarLegacyComponent
from ..variants import AC, EPS, HYBRID, X3
from .enums import StorageRunMode


class Storage(SofarLegacyComponent):
    """A storage/hybrid inverter's grid, battery and energy registers."""

    applies_to = AC | HYBRID

    run_mode = enum(0x0200, StorageRunMode, signed=False)
    voltage_r = gauge(0x0206, 0.1, signed=False, unit="V")
    current_r = gauge(0x0207, 0.01, signed=True, unit="A")
    grid_frequency = gauge(0x020C, 0.01, signed=False, unit="Hz")
    battery_power_charge = gauge(0x020D, 0.01, signed=True, unit="W")
    battery_voltage_charge = gauge(0x020E, 0.1, signed=False, unit="V")
    battery_current_charge = gauge(0x020F, 0.01, signed=True, unit="A")
    battery_capacity_charge = integer(0x0210, signed=False, unit="%")
    """Battery Capacity."""
    battery_temperature = integer(0x0211, signed=False, unit="°C")
    measured_power = gauge(0x0212, 0.01, signed=True, unit="kW")
    house_load = gauge(0x0213, 0.01, signed=False, unit="kW")
    generation_power = gauge(0x0215, 0.01, signed=False, unit="kW")
    generation_today = gauge(0x0218, 0.01, signed=False, unit="kWh")
    export_energy_today = gauge(0x0219, 0.01, signed=False, unit="kWh")
    import_energy_today = gauge(0x021A, 0.01, signed=False, unit="kWh")
    consumption_today = gauge(0x021B, 0.01, signed=False, unit="kWh")
    generation_total = uint32(0x021C, unit="kWh")
    export_energy_total = uint32(0x021E, unit="kWh")
    import_energy_total = uint32(0x0220, unit="kWh")
    consumption_total = uint32(0x0222, unit="kWh")
    battery_charge_cycle = integer(0x022C, signed=False)
    grid_voltage_r = gauge(0x0230, 0.1, signed=False, unit="V")
    grid_current_r = gauge(0x0231, 0.01, signed=False, unit="A")
    inverter_inner_temperature = integer(0x0238, signed=True, unit="°C")
    inverter_heatsink_temperature = integer(0x0239, signed=True, unit="°C")
    generation_time_today = integer(0x0242, signed=False, unit="min")
    generation_time_today_hours = uint32(0x0244, unit="h")
    """Generation Time Today."""

    @property
    def battery_input_energy(self) -> float | None:
        """Battery charge power: the positive part of ``battery_power_charge``."""
        charge = self.battery_power_charge
        return None if charge is None else max(charge, 0.0)

    @property
    def battery_output_energy(self) -> float | None:
        """Battery discharge power: the negative part, as a positive number."""
        charge = self.battery_power_charge
        return None if charge is None else max(-charge, 0.0)

    @property
    def grid_import(self) -> float | None:
        """Import power: the negative part of ``measured_power``, positive."""
        measured = self.measured_power
        return None if measured is None else max(-measured, 0.0)

    @property
    def grid_export(self) -> float | None:
        """Export power: the positive part of ``measured_power``."""
        measured = self.measured_power
        return None if measured is None else max(measured, 0.0)


class StorageThreePhase(SofarLegacyComponent):
    """The S and T phases of a three-phase storage inverter."""

    applies_to = X3 | AC | HYBRID

    voltage_s = gauge(0x0208, 0.1, signed=False, unit="V")
    current_s = gauge(0x0209, 0.01, signed=True, unit="A")
    voltage_t = gauge(0x020A, 0.1, signed=False, unit="V")
    current_t = gauge(0x020B, 0.01, signed=True, unit="A")
    grid_voltage_s = gauge(0x0232, 0.1, signed=False, unit="V")
    grid_current_s = gauge(0x0233, 0.01, signed=False, unit="A")
    grid_voltage_t = gauge(0x0234, 0.1, signed=False, unit="V")
    grid_current_t = gauge(0x0235, 0.01, signed=False, unit="A")


class StorageEps(SofarLegacyComponent):
    """Off-grid (EPS) output of a storage inverter."""

    applies_to = AC | HYBRID | EPS

    eps_voltage = gauge(0x0216, 0.1, signed=False, unit="V")
    eps_power = gauge(0x0217, 0.01, signed=False, unit="kW")


class AcBatterySettings(SofarLegacyComponent):
    """Battery floor setting of an AC-coupled storage inverter."""

    applies_to = AC
    register_space = "input"

    battery_minimum_capacity = integer(0x104D, signed=False)
