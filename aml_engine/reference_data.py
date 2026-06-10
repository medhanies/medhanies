"""Jurisdiction lists, thresholds, and other regulatory reference data.

Every list below is a point-in-time snapshot, dated as of the February 2025
FATF plenary / contemporaneous OFAC program status. Sanctions programs and
FATF listings change frequently (the FATF lists are revised at each of its
three yearly plenaries); verify against primary sources before any use
beyond this simulation:

- OFAC sanctions programs: https://ofac.treasury.gov/sanctions-programs-and-country-information
- FATF high-risk jurisdictions: https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html
"""

from __future__ import annotations

from decimal import Decimal

# ---------------------------------------------------------------------------
# OFAC sanctions programs
# ---------------------------------------------------------------------------

#: Jurisdictions under comprehensive OFAC embargoes — broadly all
#: transactions involving these countries are prohibited absent a license.
#: Iran (31 CFR Part 560), North Korea (Part 510), Cuba (Part 515),
#: Syria (Part 542). As of Feb 2025.
OFAC_COMPREHENSIVE: frozenset[str] = frozenset({"IR", "KP", "CU", "SY"})

#: Embargoed sub-national regions, modeled here as pseudo-country codes:
#: Crimea (E.O. 13685) and the so-called DNR/LNR regions of Ukraine
#: (E.O. 14065). Real payment data would identify these via city/region
#: fields; the simulation uses synthetic region codes for clarity.
OFAC_REGIONS: frozenset[str] = frozenset({"UA-CRI", "UA-DNR", "UA-LNR"})

#: Jurisdictions subject to broad sectoral / list-based OFAC programs but
#: NOT a comprehensive country embargo (Russia under E.O. 14024 et al.,
#: Belarus under E.O. 14038). Exposure warrants screening and elevated
#: monitoring rather than automatic interdiction, so these score lower
#: than the comprehensive set. As of Feb 2025.
OFAC_ELEVATED: frozenset[str] = frozenset({"RU", "BY"})

# ---------------------------------------------------------------------------
# FATF lists
# ---------------------------------------------------------------------------

#: FATF "High-Risk Jurisdictions subject to a Call for Action" (the
#: blacklist): Iran, North Korea, Myanmar. As of the Feb 2025 plenary.
FATF_BLACKLIST: frozenset[str] = frozenset({"IR", "KP", "MM"})

#: FATF "Jurisdictions under Increased Monitoring" (the greylist).
#: Snapshot as of the Feb 2025 plenary — this list changes three times a
#: year and MUST be refreshed from fatf-gafi.org before real-world use.
FATF_GREYLIST: frozenset[str] = frozenset(
    {
        "DZ",  # Algeria
        "AO",  # Angola
        "BF",  # Burkina Faso
        "BG",  # Bulgaria
        "CI",  # Côte d'Ivoire
        "CM",  # Cameroon
        "CD",  # DR Congo
        "HR",  # Croatia
        "HT",  # Haiti
        "KE",  # Kenya
        "LA",  # Lao PDR
        "LB",  # Lebanon
        "ML",  # Mali
        "MC",  # Monaco
        "MZ",  # Mozambique
        "NA",  # Namibia
        "NP",  # Nepal
        "NG",  # Nigeria
        "ZA",  # South Africa
        "SS",  # South Sudan
        "SY",  # Syria (also OFAC-comprehensive; OFAC rule takes precedence)
        "TZ",  # Tanzania
        "VE",  # Venezuela
        "VN",  # Vietnam
        "YE",  # Yemen
    }
)

# ---------------------------------------------------------------------------
# Beneficial-ownership / shell-company reference data
# ---------------------------------------------------------------------------

#: Jurisdictions commonly associated with corporate secrecy and shell
#: formation in FATF/Egmont typologies ("Concealment of Beneficial
#: Ownership", 2018). Inclusion signals elevated formation risk, not
#: wrongdoing by any particular entity.
SECRECY_HAVENS: frozenset[str] = frozenset(
    {
        "VG",  # British Virgin Islands
        "KY",  # Cayman Islands
        "PA",  # Panama
        "SC",  # Seychelles
        "BZ",  # Belize
        "MH",  # Marshall Islands
        "LI",  # Liechtenstein
        "VU",  # Vanuatu
        "WS",  # Samoa
    }
)

#: Industry codes treated as higher-risk in the FFIEC BSA/AML Examination
#: Manual (cash-intensive or historically abused for layering).
HIGH_RISK_INDUSTRIES: frozenset[str] = frozenset(
    {"MSB", "CASINO", "REAL_ESTATE", "IMPORT_EXPORT", "PRECIOUS_METALS"}
)

#: CDD Rule beneficial-ownership threshold (31 CFR 1010.230): identify each
#: natural person owning 25% or more of a legal-entity customer.
BENEFICIAL_OWNER_PCT_THRESHOLD: float = 25.0

# ---------------------------------------------------------------------------
# BSA currency thresholds
# ---------------------------------------------------------------------------

#: Currency Transaction Report filing threshold: transactions in currency
#: of more than $10,000 (31 CFR 1010.311). Note the regulation says MORE
#: THAN $10,000 — a transaction of exactly $10,000.00 does not require a
#: CTR, and a deposit of exactly $10,000 is not "just under" the threshold.
CTR_THRESHOLD: Decimal = Decimal("10000")

#: Heuristic band for "just under the CTR threshold" deposits used by the
#: structuring rules. Amounts in [$7,000, $10,000) are the classic
#: structuring profile (large enough to matter, small enough to evade).
STRUCTURING_BAND_LOW: Decimal = Decimal("7000")
STRUCTURING_BAND_HIGH: Decimal = CTR_THRESHOLD  # exclusive upper bound
