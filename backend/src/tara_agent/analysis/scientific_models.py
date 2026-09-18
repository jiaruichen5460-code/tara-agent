"""Tara MVP 科学分析的数据契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tara_agent.analysis.models import Page, TaxonMatchMode
from tara_agent.domain.contracts import Marker, ResultMetadata


class MarkerSampleSelection(BaseModel):
    """选择一个标记，并可选定部分背景样本 ID。"""

    model_config = ConfigDict(extra="forbid")

    marker: Marker
    sample_ids: list[str] | None = Field(default=None, max_length=500)

    @field_validator("sample_ids")
    @classmethod
    def validate_sample_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if not normalized or any(not value for value in normalized):
            raise ValueError("sample_ids must contain at least one non-blank ID")
        if len(normalized) != len(set(normalized)):
            raise ValueError("sample_ids must not contain duplicates")
        return normalized


class TaxonSelection(MarkerSampleSelection):
    """按照共用的明确匹配规则选择一个分类单元。"""

    taxon: str = Field(max_length=200)
    match_mode: TaxonMatchMode = TaxonMatchMode.LEVEL

    @field_validator("taxon")
    @classmethod
    def normalize_taxon(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("taxon must not be blank")
        return normalized


class TaxonAbundanceQuery(TaxonSelection):
    """请求原始测序读数和样本内相对丰度。"""

    include_zero_samples: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class TaxonAbundanceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    taxon_read_count: int = Field(ge=0)
    sample_total_read_count: int = Field(ge=0)
    relative_abundance: float | None = Field(default=None, ge=0, le=1)


class TaxonAbundanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: Marker
    taxon: str
    match_mode: TaxonMatchMode
    observations: list[TaxonAbundanceObservation]
    page: Page
    matching_asv_count: int = Field(ge=0)
    metadata: ResultMetadata


class DiversityGroup(StrEnum):
    POLAR = "polar"
    OCEAN_REGION = "ocean_region"
    DEPTH = "depth"
    SIZE_FRACTION = "size_fraction"


class DiversityQuery(MarkerSampleSelection):
    """请求所选样本未进行稀释抽样的 Alpha 多样性。"""

    taxon: str | None = Field(default=None, max_length=200)
    match_mode: TaxonMatchMode = TaxonMatchMode.LEVEL
    group_by: DiversityGroup | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("taxon")
    @classmethod
    def normalize_optional_taxon(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("taxon must not be blank")
        return normalized


class DiversityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    analysis_read_count: int = Field(ge=0)
    observed_asv_richness: int = Field(ge=0)
    shannon_index: float | None = Field(default=None, ge=0)


class DiversityGroupSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str
    sample_count: int = Field(ge=1)
    shannon_sample_count: int = Field(ge=0)
    richness_mean: float = Field(ge=0)
    richness_median: float = Field(ge=0)
    shannon_mean: float | None = Field(default=None, ge=0)
    shannon_median: float | None = Field(default=None, ge=0)


class DiversityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: Marker
    taxon: str | None
    match_mode: TaxonMatchMode
    matching_asv_count: int = Field(ge=0)
    observations: list[DiversityObservation]
    page: Page
    group_by: DiversityGroup | None
    groups: list[DiversityGroupSummary]
    metadata: ResultMetadata


class EnvironmentVariable(StrEnum):
    EVENT_LATITUDE = "event_latitude"
    EVENT_LONGITUDE = "event_longitude"
    ABS_LAT = "abs_lat"
    LOWER_SIZE_FRACTION = "lower_size_fraction"
    UPPER_SIZE_FRACTION = "upper_size_fraction"
    PAR = "par"
    DEPTH_BATHY = "depth_bathy"
    LYAPUNOV_EXP = "lyapunov_exp"
    TEMPERATURE = "temperature"
    CHLA = "chla"
    BACKSCATTERING = "backscattering"
    DEPTH_CHL_MAX = "depth_chl_max"
    MIXED_LAYER_DEPTH_SIGMA = "mixed_layer_depth_sigma"
    DEPTH_MAX_BRUNT_VAISALA = "depth_max_brunt_väisälä"
    NITRITE = "nitrite"
    PHOSPHATE = "phosphate"
    NITRATE_NITRITE = "nitrate_nitrite"
    SILICATE = "silicate"
    NSTAR = "nstar"


class EnvironmentAssociationQuery(TaxonSelection):
    """请求一次采用成对完整观测值的 Spearman 关联分析。"""

    environment_variable: EnvironmentVariable
    point_offset: int = Field(default=0, ge=0)
    point_limit: int = Field(default=200, ge=1, le=500)


class EnvironmentAssociationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    environment_value: float
    relative_abundance: float = Field(ge=0, le=1)


class EnvironmentAssociationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: Marker
    taxon: str
    match_mode: TaxonMatchMode
    environment_variable: EnvironmentVariable
    sample_count: int = Field(ge=0)
    rho: float | None = Field(default=None, ge=-1, le=1)
    p_value: float | None = Field(default=None, ge=0, le=1)
    points: list[EnvironmentAssociationPoint]
    point_page: Page
    metadata: ResultMetadata
