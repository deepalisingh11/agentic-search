from __future__ import annotations
from pydantic import BaseModel
from typing import Any, Optional

class QueryRequest(BaseModel):
    query: str
    max_results: int = 8
    custom_columns: list[str] = []
    use_fast_model: bool = True

class CellValue(BaseModel):
    value: Any
    source_url: Optional[str] = None

class EntityRow(BaseModel):
    cells: dict[str, CellValue]

class SearchResult(BaseModel):
    query: str
    entity_type: str
    columns: list[str]
    rows: list[EntityRow]
    sources_scraped: int
    sources_used: int
    from_cache: bool = False