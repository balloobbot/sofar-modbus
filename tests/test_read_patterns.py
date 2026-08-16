"""What a poll actually asks the device for.

The plugin builds its read blocks from a sorted register list, starting a new
block whenever an entity is more than ``block_size`` past the block start or
carries an explicit ``newblock``. These tests pin the equivalent here: blocks
cover every field, never exceed the device's block size, and never cross a
boundary the plugin declared.
"""

from __future__ import annotations

from collections.abc import Iterable

from modbus_connection.mock import MockModbusUnit, ReadEvent

from sofar_modbus import SofarInverter, SofarLegacyInverter
from sofar_modbus.legacy.device import _READINGS as _LEGACY_READINGS
from sofar_modbus.legacy.device import _SETTINGS as _LEGACY_SETTINGS
from sofar_modbus.model import SofarLegacyComponent
from sofar_modbus.modern import BatteryStrings1To2, BatteryStrings3To8
from sofar_modbus.variants import AC, X1, matches

from .conftest import LEGACY_HOLDING, MODERN_HOLDING, ascii_words

MODERN_BLOCK_SIZE = 48
LEGACY_BLOCK_SIZE = 100


def covered(blocks: Iterable[ReadEvent], space: str = "holding") -> set[int]:
    """Every address the blocks of one space read."""
    return {
        block.address + offset
        for block in blocks
        if block.register_type == space
        for offset in range(block.count)
    }


def field_addresses(component: object) -> set[int]:
    """Every address a component's declared fields occupy."""
    return {
        field.address + offset
        for field in component.declared_fields.values()  # type: ignore[attr-defined]
        for offset in range(field.count)
    }


def legacy_served(
    inverter: SofarLegacyInverter,
) -> list[tuple[str, SofarLegacyComponent]]:
    """Every component this inverter polls, named — pools flattened to members."""
    assert inverter.inverter_type is not None  # settled by the first update
    served = []
    for name in _LEGACY_READINGS + _LEGACY_SETTINGS:
        component: SofarLegacyComponent = getattr(inverter, name)
        if matches(inverter.inverter_type, component.applies_to):
            served.append((name, component))
    return served


async def poll(inverter: SofarInverter, unit: MockModbusUnit) -> list[ReadEvent]:
    """Run a second update, so setup's one-off serial read is excluded."""
    await inverter.async_update()
    unit.read_events.clear()
    await inverter.async_update()
    return list(unit.read_events)


async def test_a_poll_reads_every_field_of_every_polled_component(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    blocks = await poll(hybrid, mock_modbus_unit)
    read = covered(blocks)
    report = await hybrid.async_update()
    for name in report.updated:
        missing = field_addresses(getattr(hybrid, name)) - read
        assert not missing, f"{name} missed {sorted(missing)}"


async def test_readings_and_settings_read_their_own_blocks(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Neither method touches the other's registers, and together they are the poll."""
    await hybrid.async_update()

    mock_modbus_unit.read_events.clear()
    readings = await hybrid.async_update_readings()
    reading_blocks = [(b.address, b.count) for b in mock_modbus_unit.read_events]

    mock_modbus_unit.read_events.clear()
    settings = await hybrid.async_update_settings()
    setting_blocks = [(b.address, b.count) for b in mock_modbus_unit.read_events]

    mock_modbus_unit.read_events.clear()
    await hybrid.async_update()
    assert [
        (b.address, b.count) for b in mock_modbus_unit.read_events
    ] == reading_blocks + setting_blocks

    assert readings.updated.isdisjoint(settings.updated)
    assert "energy" in readings.updated  # counters are measured, not configured
    assert {"identity", "feed_in", "charger", "battery_config"} <= settings.updated
    # Nearly a quarter of the poll a caller need not pay for every cycle.
    assert sum(count for _, count in reading_blocks) == 211
    assert sum(count for _, count in setting_blocks) == 65


async def test_a_poll_reads_nothing_no_component_asked_for(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Over-reading is bounded: only inside a block a component's own plan spans.

    A Sofar refuses registers it does not implement, so a read must not wander
    into a region no polled component claims. Every address read here is either
    a field or a hole inside one component's own span.
    """
    blocks = await poll(hybrid, mock_modbus_unit)
    report = await hybrid.async_update()
    spans = [
        (min(addresses), max(addresses))
        for name in report.updated
        if (addresses := field_addresses(getattr(hybrid, name)))
    ]
    for address in covered(blocks):
        assert any(low <= address <= high for low, high in spans), hex(address)


async def test_no_block_exceeds_the_devices_block_size(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    blocks = await poll(hybrid, mock_modbus_unit)
    assert blocks  # the poll did something
    assert max(block.count for block in blocks) == MODERN_BLOCK_SIZE
    assert all(block.count <= MODERN_BLOCK_SIZE for block in blocks)
    assert all(block.register_type == "holding" for block in blocks)


async def test_each_battery_string_is_read_in_a_block_of_its_own(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The plugin marks every string a new block, so a missing one is isolated.

    Eight strings of seven registers, back to back: without the declared ranges
    they would pool into two reads and one absent string would fail both.
    """
    blocks = await poll(hybrid, mock_modbus_unit)
    battery = [b for b in blocks if 0x0604 <= b.address <= 0x063B]
    assert [(b.address, b.count) for b in battery] == [
        (0x0604 + 7 * n, 7) for n in range(8)
    ]
    declared = BatteryStrings1To2.register_ranges + BatteryStrings3To8.register_ranges
    assert sorted(declared) == [(0x0604 + 7 * n, 0x060A + 7 * n) for n in range(8)]


async def test_the_battery_config_blocks_stay_apart(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """0x1044 and 0x1048 both start a block upstream; a read never bridges them."""
    blocks = await poll(hybrid, mock_modbus_unit)
    config = [(b.address, b.count) for b in blocks if 0x1044 <= b.address <= 0x105A]
    assert config == [(0x1044, 4), (0x1048, 19)]


async def test_a_pv_only_inverter_never_touches_the_battery_registers(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[0x0445] = ascii_words("SH3E000001", 7)  # PV | X1 | GEN
    inverter = SofarInverter(mock_modbus_unit)
    blocks = await poll(inverter, mock_modbus_unit)
    read = covered(blocks)
    assert not read & set(range(0x0604, 0x066A))  # battery strings and totals
    assert not read & set(range(0x0694, 0x069C))  # battery energy counters
    assert not read & set(range(0x0504, 0x0528))  # off-grid (EPS)
    assert read >= set(range(0x0684, 0x0694))  # a PV inverter still has energy
    # A single-phase PV inverter is a fraction of the hybrid's poll.
    assert sum(b.count for b in blocks) < 150


async def test_the_extra_mppt_strings_are_only_read_where_they_exist(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[0x0445] = ascii_words("SQ1ES1000001", 7)  # MPPT10
    ten = SofarInverter(mock_modbus_unit)
    ten_blocks = await poll(ten, mock_modbus_unit)
    assert covered(ten_blocks) >= set(range(0x0584, 0x05A2)) - {0x0595}

    mock_modbus_unit.read_events.clear()
    mock_modbus_unit.holding[0x0445] = ascii_words("SH3E000001", 7)  # two MPPTs
    two = SofarInverter(mock_modbus_unit)
    two_blocks = await poll(two, mock_modbus_unit)
    assert not any(0x058A <= address <= 0x05A1 for address in covered(two_blocks))


async def test_upstreams_duplicate_pv_power_6_address_is_preserved(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """String 6's power sits on string 6's current register, as upstream has it.

    Every other string is (voltage, current, power) on consecutive registers, so
    0x0595 looks like the intended address — but the plugin reads 0x0594, and a
    device library that silently moved it would report a different register's
    value. 0x0595 is therefore never read.
    """
    from sofar_modbus.modern import PvStrings5To6

    fields = PvStrings5To6.declared_fields
    assert fields["pv_current_6"].address == 0x0594
    assert fields["pv_power_6"].address == 0x0594

    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[0x0445] = ascii_words("SQ1ES1000001", 7)
    mock_modbus_unit.holding[0x0594] = 250
    inverter = SofarInverter(mock_modbus_unit)
    blocks = await poll(inverter, mock_modbus_unit)
    assert 0x0595 not in covered(blocks)
    assert inverter.pv_5_6.pv_current_6 == inverter.pv_5_6.pv_power_6 == 2.5


# --- the older generation ----------------------------------------------------


async def test_legacy_storage_reads_one_block_plus_the_pv_strings(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The 0x0250 strings are their own blocks; upstream marks both ``newblock``."""
    await legacy_hybrid.async_update()
    mock_modbus_unit.read_events.clear()
    await legacy_hybrid.async_update()
    blocks = [
        (b.register_type, b.address, b.count) for b in mock_modbus_unit.read_events
    ]
    assert blocks == [
        # Storage and its EPS output pool: EPS's 0x0216/0x0217 sit inside the
        # storage block, so a separate read of them fetched nothing new and
        # protected nothing — storage's own bridge already spans them.
        ("holding", 0x0200, 70),  # the whole storage block, EPS included
        ("holding", 0x0250, 3),
        ("holding", 0x0253, 3),
        ("input", 0x2002, 6),  # serial number — the settings half of the poll
    ]
    assert all(count <= LEGACY_BLOCK_SIZE for _, _, count in blocks)


async def test_legacy_three_phase_pv_reads_only_the_0x0000_block(
    legacy_three_phase_pv: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await legacy_three_phase_pv.async_update()
    mock_modbus_unit.read_events.clear()
    await legacy_three_phase_pv.async_update()
    blocks = [
        (b.register_type, b.address, b.count) for b in mock_modbus_unit.read_events
    ]
    # PvCommon's temperatures (0x1B/0x1C) fall inside ThreePhasePv's span, where
    # upstream aliases them, so the two pool into the one block that spanned
    # both anyway: three reads become one, over the same 0x0000-0x0020.
    assert blocks == [
        ("holding", 0x0000, 33),
        ("input", 0x2002, 6),
    ]


async def test_legacy_readings_and_settings_read_their_own_blocks(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The serial number is all this generation has that is not a measurement.

    One request of the four, and it reads a string that cannot change — which is
    the whole payoff here; there is no writable register to read back.
    """
    await legacy_hybrid.async_update()

    mock_modbus_unit.read_events.clear()
    readings = await legacy_hybrid.async_update_readings()
    assert [
        (b.register_type, b.address, b.count) for b in mock_modbus_unit.read_events
    ] == [
        ("holding", 0x0200, 70),
        ("holding", 0x0250, 3),
        ("holding", 0x0253, 3),
    ]

    mock_modbus_unit.read_events.clear()
    settings = await legacy_hybrid.async_update_settings()
    assert [
        (b.register_type, b.address, b.count) for b in mock_modbus_unit.read_events
    ] == [("input", 0x2002, 6)]

    assert readings.updated == {"storage_block", "hybrid_pv_1", "hybrid_pv_2"}
    assert settings.updated == {"identity"}


async def test_a_legacy_ac_inverters_battery_floor_is_a_setting(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The one configured register this generation has rides with the settings."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words("SC1E1234567890", 6)
    mock_modbus_unit.input[0x104D] = 20
    inverter = SofarLegacyInverter(mock_modbus_unit, inverter_type=AC | X1)

    report = await inverter.async_update_settings()

    assert report.updated == {"identity", "battery_settings"}
    assert inverter.battery_settings.battery_minimum_capacity == 20


async def test_legacy_poll_reads_every_field_of_every_polled_component(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    await legacy_hybrid.async_update()
    for name, component in legacy_served(legacy_hybrid):
        space = "input" if component.register_space == "input" else "holding"
        missing = field_addresses(component) - covered(
            mock_modbus_unit.read_events, space
        )
        assert not missing, f"{name} missed {sorted(missing)}"


async def test_raw_dump_covers_every_polled_component(hybrid: SofarInverter) -> None:
    """Diagnostics dump the whole read map, the identity block included."""
    report = await hybrid.async_update()

    dumped = set((await hybrid.async_read_raw())["holding"])
    assert 0x0445 in dumped  # the serial number setup reads
    for name in report.updated:
        component = getattr(hybrid, name)
        missing = field_addresses(component) - dumped
        assert not missing, f"{name} missed {sorted(missing)}"
        assert component._parent is None
    # The tower serves one selected pack at a time; async_read_pack() reads it.
    assert not dumped & field_addresses(hybrid.battery_pack)


async def test_legacy_raw_dump_covers_every_polled_component(
    legacy_hybrid: SofarLegacyInverter,
) -> None:
    await legacy_hybrid.async_update()

    raw = await legacy_hybrid.async_read_raw()
    assert 0x2002 in raw["input"]  # the serial number setup reads
    for name, component in legacy_served(legacy_hybrid):
        missing = field_addresses(component) - set(raw[component.register_space])
        assert not missing, f"{name} missed {sorted(missing)}"


async def test_a_raw_dump_does_not_fire_listeners(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A download refreshes the fields without looking like a poll."""
    await hybrid.async_update()
    fired: list[str] = []
    hybrid.grid.add_update_listener(lambda: fired.append("grid"))
    hybrid.energy.add_update_listener(lambda: fired.append("energy"))

    mock_modbus_unit.holding[0x0485] = 2000
    await hybrid.async_read_raw()

    assert fired == []
    assert hybrid.grid.active_power_output_total == 20.0  # but the values are fresh


async def test_a_legacy_raw_dump_does_not_fire_listeners(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await legacy_hybrid.async_update()
    fired: list[str] = []
    legacy_hybrid.storage.add_update_listener(lambda: fired.append("storage"))
    legacy_hybrid.storage_eps.add_update_listener(lambda: fired.append("eps"))

    mock_modbus_unit.holding[0x0216] = 2400
    await legacy_hybrid.async_read_raw()

    assert fired == []
    assert legacy_hybrid.storage_eps.eps_voltage == 240.0


async def test_a_pooled_read_still_notifies_each_member(
    legacy_hybrid: SofarLegacyInverter,
) -> None:
    """Pooling changes the request count, not who hears about the result."""
    await legacy_hybrid.async_update()
    fired: list[str] = []
    legacy_hybrid.storage.add_update_listener(lambda: fired.append("storage"))
    legacy_hybrid.storage_eps.add_update_listener(lambda: fired.append("eps"))

    report = await legacy_hybrid.async_update()

    assert report.complete
    assert sorted(fired) == ["eps", "storage"]
