"""The top-level object for a current-generation Sofar inverter."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from modbus_connection import ModbusConnectionError, ModbusError
from modbus_connection.decode import decode_string

from ..model import SofarComponent, UpdateReport
from ..variants import (
    BAT_BTS,
    EPS,
    GEN,
    HYBRID,
    MPPT10,
    PM,
    PV,
    X1,
    X3,
    InverterType,
    matches,
)
from .battery import BatteryStrings1To2, BatteryStrings3To8, BatteryTotals
from .battery_pack import BatteryPack
from .energy import BatteryEnergy, EnergyTotals
from .inverter import GridOutput, Identity, InverterState
from .offgrid import OffGridSinglePhase, OffGridThreePhase, OffGridTotals
from .pv import (
    PvString3,
    PvString4,
    PvStrings1To2,
    PvStrings5To6,
    PvStrings7To8,
    PvStrings9To10,
)
from .settings import (
    BatteryActiveControl,
    BatteryConfig,
    BatteryConfigId,
    ChargerMode,
    EpsControl,
    FeedInLimit,
    ParallelControl,
    PassiveMode,
    RemoteControl,
    RtcSyncResult,
)

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

SERIAL_REGISTER = 0x0445
SERIAL_WORDS = 7
_SET_TIME_REGISTER = 0x1004
_IV_CURVE_SCAN_REGISTER = 0x1027

# Serial-number prefix -> (inverter bitmask, model name). Ported from the
# plugin's async_determineInverterType; the first matching prefix wins, so the
# table is ordered longest-first.
_SERIAL_PREFIXES: tuple[tuple[str, InverterType, str | None], ...] = (
    ("SP1ES120N6", HYBRID | X3, "HYD20KTL-3P"),
    ("SQ1ES1", PV | X3 | GEN | MPPT10, "100kW KTLX-G4"),
    ("SP1", HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P"),
    ("SP2", HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P 2nd"),
    ("ZP1", HYBRID | X3 | GEN, "HYDxx ZSS"),
    ("ZP2", HYBRID | X3 | GEN, "HYDxx ZSS"),
    ("SM2E", HYBRID | X1 | GEN, "HYDxxxxES"),
    ("ZM2E", HYBRID | X1 | GEN, "HYDxxxxKTL ZCS HP"),
    ("SH3E", PV | X1 | GEN, "4.6 KTLM-G3"),
    ("SS2E", PV | X3 | GEN, "4.4 KTLX-G3"),
    ("ZS2E", PV | X3 | GEN, "12 Azzurro KTL-V3"),
    ("SA1", PV | X1, None),
    ("SB1", PV | X1, None),
    ("SC1", PV | X3, None),
    ("SD1", PV | X3, None),
    ("SF4", PV | X3, None),
    ("SH1", HYBRID | X3 | GEN | BAT_BTS, "HYD5...8KTL-3P"),
    ("SL1", PV | X3, None),
    ("SJ2", PV | X3, None),
    ("SS1", PV | X3 | GEN, None),
)


def identify(serial: str) -> tuple[InverterType, str | None]:
    """The inverter type and model a serial number implies.

    Returns ``InverterType(0)`` for a serial the plugin does not recognise —
    which means "no component applies", so pass ``inverter_type`` to
    :class:`SofarInverter` explicitly for such a device.
    """
    for prefix, invertertype, model in _SERIAL_PREFIXES:
        if serial.startswith(prefix):
            return invertertype, model
    return InverterType(0), None


class SofarInverter:
    """A current-generation Sofar inverter reached through a ``ModbusUnit``.

    The consumer owns the connection and hands over a unit::

        inverter = SofarInverter(unit, read_eps=True)
        await inverter.async_update()
        inverter.state.system_state
        inverter.grid.active_power_output_total
        inverter.pv_1_2.pv_power_total

    Which of the sub-systems below the device actually has depends on the model,
    which the first update reads off the serial number. Every component exists as
    an attribute whatever the model; :attr:`polled_components` is the subset this
    inverter serves, and it is the only part a poll reads. A component that is
    not polled leaves all its fields at ``None``.

    ASCII framing over TCP is not supported. Build the unit from an RTU or
    RTU-over-TCP connection.
    """

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        inverter_type: InverterType | None = None,
        read_eps: bool = False,
        read_pm: bool = False,
    ) -> None:
        """Set up the sub-systems.

        ``read_eps`` and ``read_pm`` mirror the integration's options: the
        off-grid and parallel-system registers are only read when asked for,
        because an inverter without them refuses the blocks. ``inverter_type``
        skips serial-number detection for a device the table does not know.
        """
        self._unit = unit
        self._options = (EPS if read_eps else InverterType(0)) | (
            PM if read_pm else InverterType(0)
        )
        self.inverter_type: InverterType | None = None
        self.model: str | None = None
        self.serial_number: str | None = None
        if inverter_type is not None:
            self.inverter_type = inverter_type | self._options

        self.state = InverterState(unit)
        self.identity = Identity(unit)
        self.grid = GridOutput(unit)
        self.offgrid = OffGridTotals(unit)
        self.offgrid_single_phase = OffGridSinglePhase(unit)
        self.offgrid_three_phase = OffGridThreePhase(unit)
        self.pv_1_2 = PvStrings1To2(unit)
        self.pv_3 = PvString3(unit)
        self.pv_4 = PvString4(unit)
        self.pv_5_6 = PvStrings5To6(unit)
        self.pv_7_8 = PvStrings7To8(unit)
        self.pv_9_10 = PvStrings9To10(unit)
        self.battery_1_2 = BatteryStrings1To2(unit)
        self.battery_3_8 = BatteryStrings3To8(unit)
        self.battery_totals = BatteryTotals(unit)
        self.energy = EnergyTotals(unit)
        self.battery_energy = BatteryEnergy(unit)
        self.rtc_sync = RtcSyncResult(unit)
        self.feed_in = FeedInLimit(unit)
        self.eps = EpsControl(unit)
        self.battery_active_control = BatteryActiveControl(unit)
        self.parallel = ParallelControl(unit)
        self.battery_config_id = BatteryConfigId(unit)
        self.battery_config = BatteryConfig(unit)
        self.remote = RemoteControl(unit)
        self.charger = ChargerMode(unit)
        self.passive = PassiveMode(unit)
        # Read one pack at a time through async_read_pack(), never with the poll.
        self.battery_pack = BatteryPack(unit)

        self._ready = False

    @property
    def components(self) -> tuple[SofarComponent, ...]:
        """Every sub-system this generation knows, polled or not."""
        return (
            self.state,
            self.identity,
            self.grid,
            self.offgrid,
            self.offgrid_single_phase,
            self.offgrid_three_phase,
            self.pv_1_2,
            self.pv_3,
            self.pv_4,
            self.pv_5_6,
            self.pv_7_8,
            self.pv_9_10,
            self.battery_1_2,
            self.battery_3_8,
            self.battery_totals,
            self.energy,
            self.battery_energy,
            self.rtc_sync,
            self.feed_in,
            self.eps,
            self.battery_active_control,
            self.parallel,
            self.battery_config_id,
            self.battery_config,
            self.remote,
            self.charger,
            self.passive,
            self.battery_pack,
        )

    @property
    def polled_components(self) -> tuple[SofarComponent, ...]:
        """The sub-systems this inverter serves, which a poll refreshes.

        The battery tower is left out: its packs share one register block and
        have to be selected one at a time, so it is read through
        :meth:`async_read_pack` instead.
        """
        if self.inverter_type is None:
            return ()
        return tuple(
            component
            for component in self.components
            if component is not self.battery_pack
            and matches(self.inverter_type, component.applies_to)
        )

    @property
    def has_battery_tower(self) -> bool:
        """Whether this inverter reports a BTS battery tower."""
        return self.inverter_type is not None and BAT_BTS in self.inverter_type

    async def async_setup(self) -> None:
        """Read the serial number and settle the model.

        Run by the first :meth:`async_update` if the caller does not run it
        itself. A failure leaves the device unset up, so the next update retries.
        """
        words = await self._unit.read_holding_registers(SERIAL_REGISTER, SERIAL_WORDS)
        self.serial_number = decode_string(words)
        detected, model = identify(self.serial_number)
        if self.inverter_type is None:
            self.inverter_type = detected | self._options
            self.model = model
        elif model is not None:
            self.model = model
        self._ready = True

    async def async_update(self) -> UpdateReport:
        """Refresh every sub-system this inverter serves, one at a time.

        Components are read independently, the way the integration reads its
        blocks: a sub-system whose read fails keeps its previous values while
        the rest still refresh. Listeners fire only after every component has
        been tried, and only on the ones that refreshed. A failure of the link
        itself raises ``ModbusConnectionError`` instead of reporting.
        """
        if not self._ready:
            await self.async_setup()
        updated: list[SofarComponent] = []
        failed: list[tuple[SofarComponent, ModbusError]] = []
        for component in self.polled_components:
            try:
                await component.async_update(notify=False)
            except ModbusConnectionError:
                raise
            except ModbusError as err:
                failed.append((component, err))
            else:
                updated.append(component)
        for component in updated:
            component.notify()
        return UpdateReport(tuple(updated), tuple(failed))

    async def async_read_pack(self, string_nr: int, pack_nr: int) -> BatteryPack:
        """Select a BTS pack and read it.

        The tower answers for one pack at a time, so this is a two-step
        exchange rather than part of the poll. Check ``pack_id`` against the
        selection before trusting the values: a tower that has not switched
        over yet still answers, with the previous pack's data.
        """
        await self.battery_pack.async_select(string_nr, pack_nr)
        await self.battery_pack.async_update()
        return self.battery_pack

    async def async_set_time(self, when: datetime | None = None) -> None:
        """Write the inverter's clock.

        Seven registers go out at once — year, month, day, hour, minute, second
        and a trailing constant 1 the device requires. ``rtc_sync`` reports
        whether it took.
        """
        moment = when or datetime.now()
        await self._unit.write_registers(
            _SET_TIME_REGISTER,
            [
                moment.year % 100,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second,
                1,
            ],
        )

    async def async_start_iv_curve_scan(self) -> None:
        """Ask the inverter to sweep its PV strings' I-V curves."""
        await self._unit.write_register(_IV_CURVE_SCAN_REGISTER, 1)
