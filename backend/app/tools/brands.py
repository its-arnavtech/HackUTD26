"""Brand reference data from `data/brands.json`, shared by `check_link` and `check_sender`."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.config import DATA_DIR

BRANDS_PATH = DATA_DIR / "brands.json"
EXTRA_PATH = DATA_DIR / "brands_extra.json"  # L15: more real companies (see its _note)


class BrandSource(BaseModel):
    url: str
    checked: str
    says: str


class Brand(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    aliases: list[str] = Field(default_factory=list)
    brand_terms: list[str] = Field(default_factory=list)
    official_domains: list[str] = Field(default_factory=list)
    official_short_codes: list[str] = Field(default_factory=list)
    official_long_codes: list[str] = Field(default_factory=list)
    official_sender_ids: list[str] = Field(default_factory=list)
    sources: list[BrandSource] = Field(default_factory=list)

    @property
    def has_official_channels(self) -> bool:
        return bool(self.official_short_codes or self.official_long_codes or self.official_sender_ids)


def _key(name: str) -> str:
    return " ".join(name.lower().replace("-", " ").split())


@lru_cache(maxsize=4)
def load_brands(path: Path = BRANDS_PATH) -> tuple[Brand, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = list(data["brands"])
    if path == BRANDS_PATH and EXTRA_PATH.exists():  # the core registry stays first, so its matches win
        items += json.loads(EXTRA_PATH.read_text(encoding="utf-8"))["brands"]
    return tuple(Brand.model_validate(item) for item in items)


def find_brand(name: str, brands: tuple[Brand, ...] | None = None) -> Optional[Brand]:
    """Match a claimed brand by name or alias, ignoring case, hyphens and spacing."""
    wanted = _key(name)
    for brand in brands if brands is not None else load_brands():
        if wanted in {_key(brand.name), *(_key(a) for a in brand.aliases)}:
            return brand
    return None
