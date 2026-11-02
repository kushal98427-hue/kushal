"""Ticker -> sector -> agent mapping.

The mapping lives in ``config/sector_map.csv`` and is built (and documented) by
``scripts/build_sector_map.py``. This module only *reads* it; it never guesses a
sector. Symbols missing from the file are treated as ``Unclassified``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAP_PATH = Path(__file__).resolve().parents[1] / "config" / "sector_map.csv"

AGENT_BANKS = "agent1_commercial_banks"
AGENT_DEVFIN = "agent2_devbank_finance"
AGENT_HYDRO = "agent3_hydropower"
AGENT_INSURANCE = "agent4_insurance"
AGENT_OTHERS = "agent5_other_sectors"
EXCLUDED = "excluded_non_equity"
UNCLASSIFIED = "unclassified"

SECTOR_AGENTS: tuple[str, ...] = (AGENT_BANKS, AGENT_DEVFIN, AGENT_HYDRO, AGENT_INSURANCE, AGENT_OTHERS)

AGENT_TITLES_NP: dict[str, str] = {
    AGENT_BANKS: "एजेन्ट १ — वाणिज्य बैंक",
    AGENT_DEVFIN: "एजेन्ट २ — विकास बैंक तथा फाइनान्स",
    AGENT_HYDRO: "एजेन्ट ३ — जलविद्युत (हाइड्रोपावर)",
    AGENT_INSURANCE: "एजेन्ट ४ — बीमा (जीवन तथा निर्जीवन)",
    AGENT_OTHERS: "एजेन्ट ५ — अन्य क्षेत्र",
    UNCLASSIFIED: "वर्गीकरण नभएका (Unclassified)",
    EXCLUDED: "विश्लेषणबाट हटाइएका (डिबेन्चर)",
}

SECTOR_NP: dict[str, str] = {
    "Commercial Banks": "वाणिज्य बैंक",
    "Development Banks": "विकास बैंक",
    "Finance": "फाइनान्स",
    "Hydro Power": "जलविद्युत",
    "Life Insurance": "जीवन बीमा",
    "Non Life Insurance": "निर्जीवन बीमा",
    "Hotels And Tourism": "होटल तथा पर्यटन",
    "Manufacturing And Processing": "उत्पादन तथा प्रशोधन",
    "Microfinance": "लघुवित्त",
    "Investment": "लगानी",
    "Tradings": "व्यापार",
    "Others": "अन्य",
    "Mutual Fund": "म्युचुअल फण्ड",
    "Unclassified": "वर्गीकरण नभएको",
}

_EQUITY = "Equity"
_MUTUAL_FUND = "Mutual Funds"


def agent_for(sector: str, instrument_type: str) -> str:
    """Return the agent key responsible for a (sector, instrument type) pair.

    NEPSE files mutual funds and debentures under their sponsor's sector
    (e.g. a bank's debenture is ``sectorName == "Commercial Banks"``), so the
    instrument type must be checked first.
    """
    if sector == "Unclassified" or not instrument_type:
        return UNCLASSIFIED
    if instrument_type == _MUTUAL_FUND:
        return AGENT_OTHERS
    if instrument_type != _EQUITY:
        return EXCLUDED
    if sector == "Commercial Banks":
        return AGENT_BANKS
    if sector in ("Development Banks", "Finance"):
        return AGENT_DEVFIN
    if sector == "Hydro Power":
        return AGENT_HYDRO
    if sector in ("Life Insurance", "Non Life Insurance"):
        return AGENT_INSURANCE
    return AGENT_OTHERS


@dataclass(frozen=True)
class SectorInfo:
    """Classification of one symbol."""

    symbol: str
    company_name: str
    sector: str
    instrument_type: str
    nepse_status: str
    agent: str
    confidence: str
    note: str

    @property
    def group(self) -> str:
        """Display group: mutual funds get their own group regardless of sponsor sector."""
        if self.instrument_type == _MUTUAL_FUND:
            return "Mutual Fund"
        return self.sector


def unclassified(symbol: str, note: str = "not present in sector_map.csv") -> SectorInfo:
    """Build an Unclassified record for a symbol we cannot classify."""
    return SectorInfo(symbol, "", "Unclassified", "", "", UNCLASSIFIED, "none", note)


def load_sector_map(path: Path = DEFAULT_MAP_PATH) -> dict[str, SectorInfo]:
    """Load the validated mapping. Raises FileNotFoundError if missing."""
    out: dict[str, SectorInfo] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            info = SectorInfo(
                symbol=row["symbol"].strip().upper(),
                company_name=row.get("company_name", ""),
                sector=row["sector"],
                instrument_type=row.get("instrument_type", ""),
                nepse_status=row.get("nepse_status", ""),
                agent=row["agent"],
                confidence=row.get("confidence", ""),
                note=row.get("note", ""),
            )
            # Never trust the stored agent blindly: recompute from sector + instrument.
            expected = agent_for(info.sector, info.instrument_type)
            if expected != info.agent:
                info = SectorInfo(**{**info.__dict__, "agent": expected})
            out[info.symbol] = info
    return out
