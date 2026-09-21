"""用于 Tara 数据查询且与传输方式无关的数据契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tara_agent.domain.contracts import Marker, ResultMetadata


class Page(BaseModel):
    """随受限查询结果返回的分页信息。"""

    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)


class SamplingDepth(StrEnum):
    """Tara 样本背景信息中的规范深度标签。"""

    DCM = "DCM"
    FSW = "FSW"
    MES = "MES"
    MIX = "MIX"
    SRF = "SRF"
    ZZZ = "ZZZ"


_DEPTH_ALIASES = {
    "surface": SamplingDepth.SRF,
    "surface layer": SamplingDepth.SRF,
    "表层": SamplingDepth.SRF,
    "表面": SamplingDepth.SRF,
}


class FindSamplesQuery(BaseModel):
    """MVP 支持的样本筛选条件。"""

    model_config = ConfigDict(extra="forbid")

    ocean_region_contains: str | None = Field(default=None, max_length=200)
    polar: bool | None = None
    depths: list[SamplingDepth] = Field(
        default_factory=list,
        description=(
            "Tara 规范深度代码。SRF 表示表层，同时接受“表层”和 surface 作为 "
            "SRF 的别名。"
        ),
    )
    size_fractions: list[str] = Field(default_factory=list)
    temperature_min: float | None = None
    temperature_max: float | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("ocean_region_contains")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("ocean_region_contains must not be blank")
        return normalized

    @field_validator("depths", mode="before")
    @classmethod
    def normalize_depth_aliases(cls, values: object) -> object:
        if not isinstance(values, list):
            return values

        normalized = []
        for value in values:
            if not isinstance(value, str):
                normalized.append(value)
                continue
            label = " ".join(value.strip().split())
            normalized.append(_DEPTH_ALIASES.get(label.casefold(), label.upper()))
        return normalized

    @field_validator("depths")
    @classmethod
    def deduplicate_depths(cls, values: list[SamplingDepth]) -> list[SamplingDepth]:
        return list(dict.fromkeys(values))

    @field_validator("size_fractions")
    @classmethod
    def normalize_size_fractions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("filter values must not be blank")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_temperature_range(self) -> FindSamplesQuery:
        if (
            self.temperature_min is not None
            and self.temperature_max is not None
            and self.temperature_min > self.temperature_max
        ):
            raise ValueError("temperature_min must not exceed temperature_max")
        return self


class SampleSummary(BaseModel):
    """搜索结果使用的精简样本字段。"""

    model_config = ConfigDict(extra="forbid")

    sample_id_pangaea: str
    event_date: datetime
    event_latitude: float
    event_longitude: float
    ocean_region: str
    station: str
    depth: str
    size_fraction: str
    polar: str
    temperature: float | None


class SampleContext(BaseModel):
    """单个样本完整且已校验的基本与环境背景信息。"""

    model_config = ConfigDict(extra="forbid")

    sample_id_pangaea: str
    sample_id_biosamples: str
    sample_id_ena: str
    sample_material: str
    event_date: datetime
    event_latitude: float
    event_longitude: float
    depth_nominal: str
    marine_biome: str
    ocean_region: str
    biogeo_province: str
    station: str
    depth: str
    size_fraction: str
    lower_size_fraction: float
    upper_size_fraction: float | None
    depthplot: str | None
    sizeplot: str | None
    station_plot: str
    biomeplot: str
    polar: str
    abs_lat: float
    uniq: str
    complete: str
    coral_station: str
    par: float | None
    depth_bathy: int | None
    lyapunov_exp: float | None
    temperature: float | None
    chla: float | None
    backscattering: float | None
    depth_chl_max: int | None
    mixed_layer_depth_sigma: int | None
    depth_max_brunt_väisälä: int | None
    nitrite: float | None
    phosphate: float | None
    nitrate_nitrite: float | None
    silicate: float | None
    nstar: float | None


class FindSamplesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SampleSummary]
    page: Page
    metadata: ResultMetadata


class SampleInfoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: SampleContext
    metadata: ResultMetadata


class TaxonMatchMode(StrEnum):
    """明确的分类学匹配规则。"""

    LEVEL = "level"
    CONTAINS = "contains"


class FindTaxaQuery(BaseModel):
    """受限的 ASV 查询及汇总后的样本出现情况。"""

    model_config = ConfigDict(extra="forbid")

    marker: Marker
    taxon: str = Field(max_length=200)
    match_mode: TaxonMatchMode = TaxonMatchMode.LEVEL
    asv_offset: int = Field(default=0, ge=0)
    asv_limit: int = Field(default=100, ge=1, le=500)
    sample_offset: int = Field(default=0, ge=0)
    sample_limit: int = Field(default=100, ge=1, le=500)

    @field_validator("taxon")
    @classmethod
    def normalize_taxon(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("taxon must not be blank")
        return normalized


class TaxonRecord(BaseModel):
    """一个匹配的 ASV 及源数据提供的分类元数据。"""

    model_config = ConfigDict(extra="forbid")

    amplicon: str
    taxonomy: str
    confidence: str
    total: int = Field(ge=0)
    spread: int = Field(ge=0)
    sequence: str


class SampleOccurrence(BaseModel):
    """一个标记下的单个样本中，所有匹配 ASV 对应的原始测序读数。"""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    read_count: int = Field(ge=1)


class FindTaxaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: Marker
    taxon: str
    match_mode: TaxonMatchMode
    asvs: list[TaxonRecord]
    asv_page: Page
    sample_occurrences: list[SampleOccurrence]
    sample_page: Page
    metadata: ResultMetadata
