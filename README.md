# sofar-modbus

Read Sofar Solar inverters over Modbus, as typed Python objects rather than
register numbers.

The library maps Sofar's register set onto
[modbus-connection](https://github.com/balloob/modbus-connection)'s device model:
you hand it a `ModbusUnit`, call `async_update()`, and read sub-systems as
attributes. It owns no connection and no I/O policy — the caller does.

## Supported devices

Sofar ships two quite different register maps, so there are two device objects.

**`SofarInverter` — the current generation.** HYD hybrids and KTL-X / KTLM PV
inverters, over the 0x0400 (state and identity), 0x0480 (grid), 0x0500
(off-grid), 0x0580 (PV), 0x0600 (battery), 0x0680 (energy), 0x1000 (settings)
and 0x9000 (BTS battery tower) blocks. Serial prefixes: `SP1`, `SP2`, `ZP1`,
`ZP2`, `SM2E`, `ZM2E`, `SH3E`, `SS2E`, `ZS2E`, `SQ1ES1`, `SA1`, `SB1`, `SC1`,
`SD1`, `SF4`, `SH1`, `SL1`, `SJ2`, `SS1`. Includes the Azzurro and ZCS
rebadges. This is the only generation with writable registers.

**`SofarLegacyInverter` — the older generation.** The earlier PV inverters
(`SA1`, `SA3`, `SB1`, `ZA3`, `SC1`, `SD1`, `SF4`, `SH1`, `SJ2`, `SL1`, `SM1`)
and the `SE1E` / `SM1E` / `ZE1E` / `ZM1E` storage inverters, over the 0x0000 and
0x0200 blocks, with the serial number in the input-register space. Read-only.

Within a generation, what an inverter serves depends on its model: single or
three phase, PV-only or hybrid, how many MPPT trackers, whether off-grid (EPS)
and parallel-system registers exist. The first update reads the serial number
and settles this into an `InverterType` bitmask; each component declares the
mask it applies to, and a poll reads only the matching ones. Nothing else is
touched — an inverter without batteries never sees a battery register.

## Usage

```python
import asyncio

from modbus_connection import ModbusTcpParams
from modbus_connection.tmodbus import ModbusConnection
from sofar_modbus import SofarInverter


async def main() -> None:
    connection = ModbusConnection(
        ModbusTcpParams(host="192.168.1.50", port=502, framer="rtu")
    )
    try:
        inverter = SofarInverter(connection.for_unit(1), read_eps=True)
        await inverter.async_update()

        print("Model:", inverter.model, inverter.serial_number)
        print("State:", inverter.state.system_state)
        print("Grid power:", inverter.grid.active_power_output_total, "kW")
        print("PV power:", inverter.pv_1_2.pv_power_total, "kW")
        print("Battery SoC:", inverter.battery_totals.battery_capacity_total, "%")
        print("Solar today:", inverter.energy.solar_generation_today, "kWh")
    finally:
        await connection.close()


asyncio.run(main())
```

A poll reads each sub-system independently, the way the integration reads its
blocks: one slow or refused block does not take the rest of the poll with it.
`async_update()` returns an `UpdateReport` — a failed component keeps its
previous values, does not notify its listeners, and is listed by attribute
name with its error, while every other component refreshes and notifies once
the whole poll is done. Only a dead link (`ModbusConnectionError`) raises:

```python
report = await inverter.async_update()
for name, error in report.failed.items():
    print(f"{name} kept its previous values: {error}")
```

Writing works the same way — a plain field write for the registers that take
one, and a method for the registers the device insists on receiving as a block:

```python
from sofar_modbus.modern import ChargerUseMode, FeedinLimitationMode

await inverter.charger.write("charger_use_mode", ChargerUseMode.PASSIVE_MODE)
await inverter.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3000)
await inverter.passive.async_write_power(
    grid_power=-2000, battery_min=0, battery_max=5000
)
await inverter.active_power_control.async_write_active_power_limit(True, 70)
```

`active_power_control` is a live throttle on the inverter's own output — distinct
from `feed_in`, which caps power exported to the grid. It applies to PV-only
inverters as well as hybrids, and takes effect within seconds.

A BTS battery tower multiplexes every pack onto one register block, so packs are
read one at a time rather than polled:

```python
if inverter.has_battery_tower:
    pack = await inverter.async_read_pack(string_nr=0, pack_nr=0)
    print(pack.pack_serial_number, pack.soc, pack.cell_1_voltage)
```

## ASCII over TCP is not supported

Sofar inverters are reached over RTU or RTU-over-TCP. This library never accepts
or forwards `framer="ascii"`, and it exposes no connect helper that could: the
caller builds the `ModbusUnit` and hands it over. Build it from an RTU serial or
RTU-over-TCP connection — an ASCII-framed TCP connection is unsupported and
untested, and nothing here works around it.

## Attribution

The register maps are derived from
[homeassistant-solax-modbus](https://github.com/wills106/homeassistant-solax-modbus)
(Apache-2.0), specifically its `plugin_sofar.py` and `plugin_sofar_old.py`. This
library keeps that project's field keys, scale factors, units and per-model
filtering, and is released under the same licence.

Where upstream declares two entities on one register, or the same key twice,
this library keeps both rather than picking a winner — the docstring on each
field carries upstream's name, and the tests spell out the cases.
