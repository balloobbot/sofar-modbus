"""The current-generation register map, decoded over the mock backend."""

from __future__ import annotations

from datetime import datetime

import pytest
from modbus_connection.mock import MockModbusUnit, WriteEvent

from sofar_modbus import SofarInverter
from sofar_modbus.modern import (
    ChargerUseMode,
    EpsControlMode,
    Fault1,
    Fault5,
    FeedinLimitationMode,
    ParallelMasterslave,
    PassiveModeTimeoutAction,
    PowerControlFlags,
    RemoteSwitchOnOff,
    SyncRtcResult,
    SystemState,
    identify,
)
from sofar_modbus.variants import BAT_BTS, EPS, GEN, HYBRID, MPPT10, PM, PV, X1, X3

from .conftest import HYBRID_SERIAL, MODERN_HOLDING, ascii_words


def test_identify_maps_serial_prefixes() -> None:
    assert identify("SP1ES120N6ABCD") == (HYBRID | X3, "HYD20KTL-3P")
    assert identify(HYBRID_SERIAL) == (HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P")
    assert identify("SQ1ES1000001") == (PV | X3 | GEN | MPPT10, "100kW KTLX-G4")
    assert identify("SH3E000001") == (PV | X1 | GEN, "4.6 KTLM-G3")
    assert identify("SA1000001") == (PV | X1, None)
    assert identify("NOPE00001") == (0, None)


def test_the_longer_prefix_wins() -> None:
    """SP1ES120N6 is a plain HYD20KTL-3P, not the battery-tower SP1 family."""
    specific, _ = identify("SP1ES120N6ABCD")
    generic, _ = identify("SP1ES999999")
    assert BAT_BTS not in specific
    assert BAT_BTS in generic


async def test_setup_reads_the_serial_and_settles_the_model(
    hybrid: SofarInverter,
) -> None:
    await hybrid.async_update()
    assert hybrid.serial_number == HYBRID_SERIAL
    assert hybrid.model == "HYDxxKTL-3P"
    assert hybrid.inverter_type == HYBRID | X3 | GEN | BAT_BTS | EPS | PM
    assert hybrid.has_battery_tower is True


async def test_polled_components_covers_both_poll_lists(
    hybrid: SofarInverter,
) -> None:
    assert hybrid.polled_components is None
    await hybrid.async_update()
    assert hybrid._readings is not None and hybrid._settings is not None
    assert hybrid.polled_components == tuple(hybrid._readings + hybrid._settings)


async def test_settings_components_names_what_the_settings_poll_reads(
    hybrid: SofarInverter,
) -> None:
    """The accessor is the split itself, not a copy of it.

    A caller routing per component cannot drift from what each poll touches.
    """
    assert hybrid.settings_components is None
    settings = await hybrid.async_update_settings()
    readings = await hybrid.async_update_readings()

    split = hybrid.settings_components
    polled = hybrid.polled_components
    assert split is not None and polled is not None  # settled by the polls above
    assert set(split) == settings.updated | set(settings.failed)
    assert set(polled) - set(split) == readings.updated | set(readings.failed)


async def test_prime_sets_up_polling_like_async_setup_would(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A caller that already knows the identity can skip the I/O in async_setup()."""
    await hybrid.async_update()  # the real thing prime() is meant to mirror

    primed = SofarInverter(
        mock_modbus_unit,
        inverter_type=HYBRID | X3 | GEN | BAT_BTS,
        read_eps=True,
        read_pm=True,
    )
    primed.prime(HYBRID_SERIAL, "HYDxxKTL-3P")

    assert primed.serial_number == HYBRID_SERIAL
    assert primed.model == "HYDxxKTL-3P"
    assert primed.inverter_type == hybrid.inverter_type
    assert primed.polled_components == hybrid.polled_components


def test_prime_requires_inverter_type_from_the_constructor(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    device = SofarInverter(mock_modbus_unit)
    with pytest.raises(ValueError, match="prime\\(\\) requires inverter_type"):
        device.prime(HYBRID_SERIAL, "HYDxxKTL-3P")


async def test_state_and_faults(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.state.system_state is SystemState.GRID_CONNECTED
    assert hybrid.state.fault_1 == Fault1(0)  # 0 decodes to the empty flag
    assert (
        hybrid.state.fault_5
        == Fault5.ID069_PV_OVERVOLTAGE | Fault5.ID070_BATTERY_OVER_VOLTAGE
    )
    assert hybrid.state.waiting_time == 30
    assert hybrid.state.inverter_temperature_1 == 45
    assert hybrid.state.module_temperature_1 == -10  # signed


async def test_identity_and_clock(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.identity.serial_number == HYBRID_SERIAL
    assert hybrid.identity.hardware_version == "V1"
    assert hybrid.identity.software_version == "V210"
    assert hybrid.identity.rtc == datetime(2025, 8, 12, 14, 30, 5)


async def test_a_blank_clock_reads_as_no_value(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Month 0 is not a date; the property says so rather than raising."""
    mock_modbus_unit.holding[0x042D] = 0
    await hybrid.async_update()
    assert hybrid.identity.rtc is None


async def test_grid_output(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    grid = hybrid.grid
    assert grid.grid_frequency == pytest.approx(50.01)
    assert grid.active_power_output_total == pytest.approx(12.34)
    assert grid.reactive_power_output_total == pytest.approx(-1.0)  # signed
    assert grid.apparent_power_output_total == pytest.approx(12.5)
    assert grid.voltage_l1 == pytest.approx(230.1)
    assert grid.current_output_l1 == pytest.approx(5.43)
    assert grid.power_factor_output_l1 == pytest.approx(0.998)
    assert grid.voltage_line_l3 == pytest.approx(398.1)


async def test_off_grid_is_read_only_when_eps_is_enabled(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    without_eps = SofarInverter(mock_modbus_unit)
    report = await without_eps.async_update()
    assert without_eps.offgrid.offgrid_frequency is None
    assert "offgrid" not in report.updated
    assert not any(0x0504 <= b.address <= 0x0527 for b in mock_modbus_unit.read_events)


async def test_off_grid_three_phase(hybrid: SofarInverter) -> None:
    report = await hybrid.async_update()
    assert hybrid.offgrid.offgrid_frequency == pytest.approx(49.98)
    assert hybrid.offgrid.active_power_offgrid_total == pytest.approx(3.0)
    assert hybrid.offgrid_three_phase.offgrid_voltage_l1 == pytest.approx(229.5)
    assert hybrid.offgrid_three_phase.offgrid_voltage_l2 == pytest.approx(228.8)
    # The single-phase layout overlaps the three-phase one at 0x050A; only the
    # component matching this inverter's phase count is polled.
    assert "offgrid_single_phase" not in report.updated
    assert hybrid.offgrid_single_phase.offgrid_voltage is None


async def test_pv_strings(hybrid: SofarInverter) -> None:
    report = await hybrid.async_update()
    assert hybrid.pv_1_2.pv_voltage_1 == pytest.approx(380.5)
    assert hybrid.pv_1_2.pv_current_1 == pytest.approx(8.12)
    assert hybrid.pv_1_2.pv_power_1 == pytest.approx(3.09)
    assert hybrid.pv_1_2.pv_voltage_2 == pytest.approx(371.2)
    assert hybrid.pv_1_2.pv_power_total == pytest.approx(5.8)
    # A two-MPPT inverter never reads strings 3 and up.
    assert "pv_3" not in report.updated
    assert hybrid.pv_3.pv_voltage_3 is None


async def test_extra_mppt_strings_appear_on_a_ten_mppt_inverter(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[0x0445] = ascii_words("SQ1ES1000001", 7)
    mock_modbus_unit.holding[0x059F] = 3600  # PV voltage 10 -> 360.0 V
    inverter = SofarInverter(mock_modbus_unit)
    report = await inverter.async_update()
    assert inverter.model == "100kW KTLX-G4"
    for name in ("pv_3", "pv_4", "pv_5_6", "pv_7_8", "pv_9_10"):
        assert name in report.updated
    assert inverter.pv_9_10.pv_voltage_10 == pytest.approx(360.0)
    # PV-only: no battery, no hybrid-only settings.
    assert "battery_1_2" not in report.updated
    assert "charger" not in report.updated


async def test_battery_strings_and_totals(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.battery_1_2.battery_voltage_1 == pytest.approx(204.8)
    assert hybrid.battery_1_2.battery_current_1 == pytest.approx(-10.0)  # signed
    assert hybrid.battery_1_2.battery_power_1 == pytest.approx(-20.0)
    assert hybrid.battery_1_2.battery_capacity_1 == 87
    assert hybrid.battery_1_2.battery_charge_cycle_1 == 412
    assert hybrid.battery_1_2.battery_voltage_2 == pytest.approx(204.4)
    assert hybrid.battery_3_8.battery_voltage_3 == pytest.approx(204.0)
    assert hybrid.battery_totals.battery_power_total == pytest.approx(-6.0)
    assert hybrid.battery_totals.battery_capacity_total == 87


async def test_energy_counters(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.energy.solar_generation_today == pytest.approx(12.34)  # uint32
    assert hybrid.energy.solar_generation_total == pytest.approx(10000.0)
    assert hybrid.energy.load_consumption_today == pytest.approx(9.87)
    assert hybrid.battery_energy.battery_input_energy_today == pytest.approx(5.5)


async def test_settings(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.rtc_sync.sync_rtc_result is SyncRtcResult.SUCCESSFUL
    assert (
        hybrid.feed_in.feedin_limitation_mode
        is FeedinLimitationMode.ENABLED_FEED_IN_LIMITATION
    )
    assert hybrid.feed_in.feedin_max_power == pytest.approx(5000)  # raw * 100
    assert hybrid.eps.eps_control is EpsControlMode.TURN_ON_ENABLE_COLD_START
    assert hybrid.battery_active_control.battery_active_control is True
    assert hybrid.parallel.parallel_control is True
    assert hybrid.parallel.parallel_masterslave is ParallelMasterslave.MASTER
    assert hybrid.parallel.parallel_address == 3
    assert hybrid.battery_config.bat_config_charging_voltage == pytest.approx(256.0)
    assert hybrid.remote.remote_switch_on_off is RemoteSwitchOnOff.ON
    assert hybrid.active_power_control.power_control is PowerControlFlags.ACTIVE_POWER
    assert hybrid.active_power_control.active_power_export_limit == pytest.approx(70.0)
    assert hybrid.charger.charger_use_mode is ChargerUseMode.TIME_OF_USE
    assert hybrid.passive.passive_mode_timeout == 600
    assert (
        hybrid.passive.passive_mode_timeout_action
        is PassiveModeTimeoutAction.RETURN_TO_PREVIOUS_MODE
    )
    assert hybrid.passive.passive_mode_grid_power == -2000  # int32
    assert hybrid.passive.passive_mode_battery_power_max == 3000


# --- writes -----------------------------------------------------------------


async def test_write_charger_mode(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The mode register takes FC16 even though it is a single register."""
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.charger.write("charger_use_mode", ChargerUseMode.PASSIVE_MODE)
    assert [(e.address, e.values, e.function_code) for e in events] == [
        (0x1110, [3], 0x10)
    ]
    assert await mock_modbus_unit.read_holding_registers(0x1110, 1) == [3]


async def test_write_remote_switch(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.remote.write("remote_switch_on_off", RemoteSwitchOnOff.OFF)
    assert await mock_modbus_unit.read_holding_registers(0x1104, 1) == [0]


async def test_parallel_address_is_validated(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.parallel.write("parallel_address", 7)
    assert await mock_modbus_unit.read_holding_registers(0x1037, 1) == [7]
    with pytest.raises(ValueError, match="outside 0-10"):
        await hybrid.parallel.write("parallel_address", 11)
    assert await mock_modbus_unit.read_holding_registers(0x1037, 1) == [7]  # unchanged


async def test_feed_in_limit_writes_both_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3000)
    assert [(e.address, e.values) for e in events] == [(0x1023, [0, 30])]
    with pytest.raises(ValueError, match="multiple of 100"):
        await hybrid.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3050)


async def test_active_power_limit_writes_both_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.active_power_control.async_write_active_power_limit(True, 30)
    await hybrid.active_power_control.async_write_active_power_limit(False, 80)
    assert [(e.address, e.values) for e in events] == [
        (0x1105, [int(PowerControlFlags.ACTIVE_POWER), 300]),
        (0x1105, [0, 800]),
    ]
    with pytest.raises(ValueError, match="outside 0-100"):
        await hybrid.active_power_control.async_write_active_power_limit(True, 101)


async def test_eps_control_writes_the_reserved_wait_time_as_zero(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.eps.async_write_control(EpsControlMode.TURN_OFF)
    assert [(e.address, e.values) for e in events] == [(0x1029, [0, 0])]


async def test_passive_mode_writes(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.passive.async_write_timeout(
        300, PassiveModeTimeoutAction.FORCE_STANDBY
    )
    await hybrid.passive.async_write_power(-2000, 0, 5000)
    assert [(e.address, e.values) for e in events] == [
        (0x1184, [300, 0]),
        # three signed 32-bit values, big-endian word order
        (0x1187, [0xFFFF, 0xF830, 0, 0, 0, 5000]),
    ]


async def test_set_time_writes_seven_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The device requires a trailing constant 1 alongside the six date parts."""
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.async_set_time(datetime(2025, 8, 12, 14, 30, 5))
    assert [(e.address, e.values) for e in events] == [
        (0x1004, [25, 8, 12, 14, 30, 5, 1])
    ]


async def test_iv_curve_scan(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.async_start_iv_curve_scan()
    assert [(e.address, e.values) for e in events] == [(0x1027, [1])]


# --- the BTS battery tower ---------------------------------------------------


async def test_battery_pack_is_selected_then_read(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)
    pack = await hybrid.async_read_pack(string_nr=1, pack_nr=2)
    assert [(e.address, e.values) for e in writes] == [(0x9020, [(2 << 8) | 1])]
    assert pack.pack_model == "BTS5K"
    assert pack.string_count == 2
    assert pack.packs_per_string == 3
    assert pack.total_voltage == pytest.approx(51.2)
    assert pack.total_current == pytest.approx(-5.0)
    assert pack.soc == 88
    assert pack.pack_serial_number == "BTSPACK000000001"
    assert pack.cell_1_voltage == pytest.approx(3.3)
    assert pack.cell_16_voltage == pytest.approx(3.298)
    assert pack.pack_temperature_1 == pytest.approx(24.5)
    assert pack.pack_remaining_capacity == pytest.approx(100.0)
    assert pack.pack_time == datetime(2025, 8, 12, 14, 30, 5)


async def test_the_battery_tower_is_never_part_of_a_poll(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Packs share one register block, so a poll cannot read them all."""
    report = await hybrid.async_update()
    assert "battery_pack" not in report.updated
    assert not any(b.address >= 0x9000 for b in mock_modbus_unit.read_events)
