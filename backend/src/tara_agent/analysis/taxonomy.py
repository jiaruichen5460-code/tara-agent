"""查询服务与科学分析服务共用的分类学匹配规则。"""

import polars as pl

from tara_agent.analysis.models import TaxonMatchMode


def taxonomy_predicate(taxon: str, match_mode: TaxonMatchMode) -> pl.Expr:
    """构建不区分大小写、按字面值匹配的分类学筛选表达式。"""

    taxonomy = pl.col("taxonomy").str.to_lowercase()
    normalized = taxon.lower()
    if match_mode is TaxonMatchMode.LEVEL:
        return taxonomy.str.split(";").list.contains(normalized)
    return taxonomy.str.contains(normalized, literal=True)
