"""Shared taxonomy matching rules for query and scientific services."""

import polars as pl

from tara_agent.analysis.models import TaxonMatchMode


def taxonomy_predicate(taxon: str, match_mode: TaxonMatchMode) -> pl.Expr:
    """Build a case-insensitive, literal taxonomy predicate."""

    taxonomy = pl.col("taxonomy").str.to_lowercase()
    normalized = taxon.lower()
    if match_mode is TaxonMatchMode.LEVEL:
        return taxonomy.str.split(";").list.contains(normalized)
    return taxonomy.str.contains(normalized, literal=True)
