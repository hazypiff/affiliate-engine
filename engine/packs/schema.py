"""Niche pack manifest validation. A pack is one installable directory:
pack.yaml + programs.yaml + compliance.json + prompts/ + data/."""

from pydantic import BaseModel, Field


class VerticalSpec(BaseModel):
    slug: str
    name: str
    domain: str


class DatasetSpec(BaseModel):
    slug: str
    adapter: str = "csv"
    file: str
    entity_key: str


class PageTypeSpec(BaseModel):
    type: str
    prompt: str  # path relative to pack dir
    slots: list[str] = Field(default_factory=list)


class SlotSpec(BaseModel):
    slug: str
    description: str = ""


class TestCellSpec(BaseModel):
    slug: str
    page_target: int = 30


class OfferSpec(BaseModel):
    slug: str
    name: str
    url_template: str
    payout_amount: float
    geo_allow: list[str] = Field(default_factory=list)


class ProgramSpec(BaseModel):
    slug: str
    name: str
    network: str
    payout_model: str
    cookie_window_days: int = 30
    payout: dict = Field(default_factory=dict)
    offers: list[OfferSpec]


class ComplianceSpec(BaseModel):
    required_disclosures: list[str]
    banned_phrases: list[str] = Field(default_factory=list)
    geo_default_deny: bool = False


class TrafficSpec(BaseModel):
    """Organic-growth config: drives keyword discovery, brief planning, and the
    daily-growth loop. Intents map to page types the factory can build."""

    audience: str = ""
    country: str = "US"
    seed_keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    intents: list[str] = Field(
        default_factory=lambda: ["review", "comparison", "alternatives", "best", "pricing"]
    )
    daily_publish_limit: int = 3
    min_opportunity_score: float = 0.35


class PackManifest(BaseModel):
    slug: str
    version: str
    name: str
    vertical: VerticalSpec
    dataset: DatasetSpec
    page_types: list[PageTypeSpec]
    slots: list[SlotSpec]
    test_cell: TestCellSpec
    min_facts_per_page: int = 6
    uniqueness_cosine_ceiling: float = 0.85
    traffic: TrafficSpec = Field(default_factory=TrafficSpec)
