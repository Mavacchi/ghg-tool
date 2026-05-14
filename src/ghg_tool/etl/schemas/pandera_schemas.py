"""Pandera DataFrameSchema definitions for Scope 1, 2, and 3 CSVs.

Each schema corresponds to the full column set declared in requirements.md
FR-01/FR-02/FR-03.  All values arrive as strings from the CSV reader; pandera
coerces and validates.

Business rules validated here:
- Non-negative Quantità (DQ-CRIT-03)
- Allowed Codice_Sito values (7 sites per requirements.md §5.2)
- Allowed Voce_S2 values (FR-02)
- Allowed Categoria_S3 range (FR-03)
- Non-null mandatory fields (DQ-CRIT-02)
"""

from __future__ import annotations

import pandera as pa
from pandera import Column, DataFrameSchema

_VALID_SITI = [
    "IANO", "VIANO", "VIANO_GARGOLA",
    "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO",
]
_VALID_QUALITA = ["P", "D", "E", "U", "S"]
_VALID_STATO = ["Definitivo", "Provvisorio", "Stimato"]

scope1_schema = DataFrameSchema(
    columns={
        "Scope": Column(int, pa.Check.equal_to(1), coerce=True),
        "Anno": Column(
            int,
            pa.Check.in_range(2020, 2099),
            coerce=True,
        ),
        "Codice_Sito": Column(
            str,
            pa.Check.isin(_VALID_SITI),
        ),
        "Categoria_S1": Column(str, pa.Check.str_length(min_value=1)),
        "Combustibile": Column(str, pa.Check.str_length(min_value=1)),
        "Quantità": Column(
            float,
            pa.Check.greater_than_or_equal_to(0),
            coerce=True,
            nullable=False,
        ),
        "Unità": Column(str, pa.Check.str_length(min_value=1)),
        "Fonte_Dato": Column(str, pa.Check.str_length(min_value=1)),
        "Qualità_Dato": Column(str, pa.Check.isin(_VALID_QUALITA)),
        "Stato_Dato": Column(str, pa.Check.isin(_VALID_STATO)),
        "Note": Column(str, nullable=True, required=False),
    },
    coerce=True,
    strict=False,  # allow extra columns (provenance columns added by transforms)
)

scope2_schema = DataFrameSchema(
    columns={
        "Scope": Column(int, pa.Check.equal_to(2), coerce=True),
        "Anno": Column(int, pa.Check.in_range(2020, 2099), coerce=True),
        "Codice_Sito": Column(str, pa.Check.isin(_VALID_SITI)),
        "Voce_S2": Column(
            str,
            pa.Check.isin(["EE_Acquistata_GO", "EE_Acquistata_Grid"]),
        ),
        "Quantità": Column(
            float,
            pa.Check.greater_than_or_equal_to(0),
            coerce=True,
            nullable=False,
        ),
        "Unità": Column(str, pa.Check.equal_to("kWh")),
        "Strumento_MB": Column(str, nullable=True, required=False),
        "Fonte_Dato": Column(str, pa.Check.str_length(min_value=1)),
        "Qualità_Dato": Column(str, pa.Check.isin(_VALID_QUALITA)),
        "Stato_Dato": Column(str, pa.Check.isin(_VALID_STATO)),
        "Note": Column(str, nullable=True, required=False),
    },
    coerce=True,
    strict=False,
)

scope3_schema = DataFrameSchema(
    columns={
        "Scope": Column(int, pa.Check.equal_to(3), coerce=True),
        "Anno": Column(int, pa.Check.in_range(2020, 2099), coerce=True),
        "Categoria_S3": Column(int, pa.Check.in_range(1, 15), coerce=True),
        "Sottocategoria": Column(str, pa.Check.str_length(min_value=1)),
        "Metodo": Column(str, pa.Check.str_length(min_value=1)),
        "Combustibile": Column(str, nullable=True, required=False),
        "Quantità": Column(
            float,
            pa.Check.greater_than_or_equal_to(0),
            coerce=True,
            nullable=False,
        ),
        "Unità": Column(str, pa.Check.str_length(min_value=1)),
        # Fonte/Qualità/Stato validated AFTER FR-37 defaulting (hence nullable here)
        "Fonte_Dato": Column(str, nullable=True, required=False),
        "Qualità_Dato": Column(str, nullable=True, required=False),
        "Stato_Dato": Column(str, nullable=True, required=False),
        "Note": Column(str, nullable=True, required=False),
    },
    coerce=True,
    strict=False,
)
