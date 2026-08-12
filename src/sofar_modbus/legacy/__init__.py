"""The older Sofar register map (upstream ``plugin_sofar_old.py``).

Covers the earlier SA/SB/SC/SD/SF/SJ/SL PV inverters and the SE1E/SM1E/ZE1E/ZM1E
storage inverters, which use the 0x0000 (PV) and 0x0200 (storage) blocks and
report their serial number in the input-register space. Read-only.
"""

from .device import SofarLegacyInverter, identify
from .enums import PvRunMode, StorageRunMode
from .identity import LegacyIdentity
from .pv import HybridPvString1, HybridPvString2, PvCommon, SinglePhasePv, ThreePhasePv
from .storage import AcBatterySettings, Storage, StorageEps, StorageThreePhase

__all__ = [
    "AcBatterySettings",
    "HybridPvString1",
    "HybridPvString2",
    "LegacyIdentity",
    "PvCommon",
    "PvRunMode",
    "SinglePhasePv",
    "SofarLegacyInverter",
    "Storage",
    "StorageEps",
    "StorageRunMode",
    "StorageThreePhase",
    "ThreePhasePv",
    "identify",
]
