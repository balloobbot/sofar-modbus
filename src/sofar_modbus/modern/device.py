"""The top-level object for a current-generation Sofar inverter."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from modbus_connection import ModbusConnectionError, ModbusError, ModbusTimeoutError
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
    ActivePowerControl,
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

# Every component attribute a poll may refresh, in read order. battery_pack is
# absent: its packs share one register block and are read via async_read_pack().
_POLLED = (
    "state",
    "identity",
    "grid",
    "offgrid",
    "offgrid_single_phase",
    "offgrid_three_phase",
    "pv_1_2",
    "pv_3",
    "pv_4",
    "pv_5_6",
    "pv_7_8",
    "pv_9_10",
    "battery_1_2",
    "battery_3_8",
    "battery_totals",
    "energy",
    "battery_energy",
    "rtc_sync",
    "feed_in",
    "eps",
    "battery_active_control",
    "parallel",
    "battery_config_id",
    "battery_config",
    "remote",
    "active_power_control",
    "charger",
    "passive",
)
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
    an attribute whatever the model; a poll reads only the subset this inverter
    serves and reports it by attribute name. A component that is not polled
    leaves all its fields at ``None``.

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
        self.active_power_control = ActivePowerControl(unit)
        self.charger = ChargerMode(unit)
        self.passive = PassiveMode(unit)
        # Read one pack at a time through async_read_pack(), never with the poll.
        self.battery_pack = BatteryPack(unit)

        self._polled: list[str] | None = None

    @property
    def has_battery_tower(self) -> bool:
        """Whether this inverter reports a BTS battery tower."""
        return self.inverter_type is not None and BAT_BTS in self.inverter_type

    async def async_setup(self) -> None:
        """Read the serial number, settle the model, and pick what to poll.

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
        inverter_type = self.inverter_type
        self._polled = [
            name
            for name in _POLLED
            if matches(inverter_type, getattr(self, name).applies_to)
        ]

    def prime(self, serial_number: str, model: str | None) -> None:
        """Set up polling from an already-known identity.

        Skips the serial-number read `async_setup()` would otherwise need, for
        callers that already know a device's identity from a previous probe
        (e.g. a Home Assistant config entry's unique_id) and want to avoid
        blocking on I/O to re-read it. `inverter_type` must already be set on
        this instance -- pass it to the constructor. Mirrors `async_setup()`'s
        post-read bookkeeping exactly.
        """
        if self.inverter_type is None:
            raise ValueError(
                "prime() requires inverter_type to already be set "
                "(pass it to the constructor)"
            )
        self.serial_number = serial_number
        self.model = model
        self._polled = [
            name
            for name in _POLLED
            if matches(self.inverter_type, getattr(self, name).applies_to)
        ]

    async def async_update(self) -> UpdateReport:
        """Refresh every sub-system this inverter serves, one at a time.

        Components are read independently, the way the integration reads its
        blocks: a sub-system whose read fails keeps its previous values while
        the rest still refresh. Listeners fire only after every component has
        been tried, and only on the ones that refreshed. A failure of the link
        itself raises ``ModbusConnectionError`` instead of reporting, and so
        does a timeout before anything has answered: a silent inverter is not
        walked component by component, paying a timeout for each.
        """
        if self._polled is None:
            await self.async_setup()
        assert self._polled is not None  # async_setup() builds it
        updated: set[str] = set()
        failed: dict[str, ModbusError] = {}
        for name in self._polled:
            component: SofarComponent = getattr(self, name)
            try:
                await component.async_update(notify=False)
            except ModbusConnectionError:
                raise
            except ModbusTimeoutError as err:
                if not updated and not failed:
                    raise  # nothing answered at all: assume the rest time out too
                failed[name] = err
            except ModbusError as err:
                failed[name] = err
            else:
                updated.add(name)
        for name in updated:
            fresh: SofarComponent = getattr(self, name)
            fresh.notify()
        return UpdateReport(updated, failed)

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Every register this inverter reads, undecoded — for diagnostics.

        The serial number setup reads sits inside ``identity``, which is polled,
        so the polled components already cover it. Left out are the blocks this
        inverter does not serve, and ``battery_pack``: the tower answers for one
        selected pack at a time, so a dump of that block would be whichever pack
        happened to be selected, with nothing to say which. Read packs through
        :meth:`async_read_pack`. Nothing notifies: a download is not a poll.
        The first call sets the inverter up.
        """
        if self._polled is None:
            await self.async_setup()
        assert self._polled is not None  # async_setup() builds it
        raw: dict[str, dict[int, int | bool]] = {}
        for name in self._polled:
            component: SofarComponent = getattr(self, name)
            for space, values in (await component.async_read_raw(notify=False)).items():
                raw.setdefault(space, {}).update(values)
        return raw

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
