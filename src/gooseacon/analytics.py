"""Validated Search Analytics requests and row pagination."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Dimension = Literal["country", "device", "page", "query", "searchAppearance", "date", "hour"]
FilterDimension = Literal["country", "device", "page", "query", "searchAppearance"]
SearchType = Literal["web", "image", "video", "news", "discover", "googleNews"]
Aggregation = Literal["auto", "byPage", "byProperty", "byNewsShowcasePanel"]
DataState = Literal["final", "all", "hourly_all"]


class DimensionFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: FilterDimension
    operator: Literal[
        "equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"
    ] = "equals"
    expression: str = Field(min_length=1)


class FilterGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groupType: Literal["and"] = "and"
    filters: list[DimensionFilter] = Field(min_length=1)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    dimensions: list[Dimension] = Field(default_factory=list)
    dimension_filter_groups: list[FilterGroup] = Field(
        default_factory=list, alias="dimensionFilterGroups"
    )
    row_limit: int = Field(default=1000, ge=1, le=25000, alias="rowLimit")
    start_row: int = Field(default=0, ge=0, alias="startRow")
    search_type: SearchType = Field(default="web", alias="type")
    aggregation_type: Aggregation = Field(default="auto", alias="aggregationType")
    data_state: DataState = Field(default="final", alias="dataState")

    @model_validator(mode="before")
    @classmethod
    def legacy_type(cls, value: Any) -> Any:
        if isinstance(value, dict) and "searchType" in value:
            value = dict(value)
            value.setdefault("type", value.pop("searchType"))
        return value

    @field_validator("dimensions")
    @classmethod
    def unique_dimensions(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Dimensions must not contain duplicates")
        return value

    @model_validator(mode="after")
    def check_range(self) -> Query:
        if self.start_date > self.end_date:
            raise ValueError("start date must be on or before end date")
        if self.aggregation_type == "byProperty":
            page_filter = any(
                f.dimension == "page" for g in self.dimension_filter_groups for f in g.filters
            )
            if "page" in self.dimensions or page_filter:
                raise ValueError("byProperty cannot group or filter by page")
            if self.search_type in {"discover", "googleNews"}:
                raise ValueError("byProperty is not supported for discover/googleNews")
        if "hour" in self.dimensions and self.data_state != "hourly_all":
            raise ValueError("The hour dimension requires --data-state hourly_all")
        return self

    def body(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


def run_query(
    service: Any, site: str, query: Query, *, all_rows: bool = False, max_rows: int = 100000
) -> dict:
    """Page API rows without claiming a complete export of Google's underlying data."""
    body = query.body()
    if not all_rows:
        return service.searchanalytics().query(siteUrl=site, body=body).execute(num_retries=3)
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    rows: list[dict] = []
    result: dict = {}
    offset = query.start_row
    exhausted = False
    while len(rows) < max_rows:
        limit = min(query.row_limit, max_rows - len(rows))
        page = (
            service.searchanalytics()
            .query(siteUrl=site, body={**body, "startRow": offset, "rowLimit": limit})
            .execute(num_retries=3)
        )
        batch = page.get("rows", [])
        result.update({k: v for k, v in page.items() if k != "rows"})
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < limit:
            exhausted = True
            break
    return {
        **result,
        "rows": rows,
        "pagination": {
            "startRow": query.start_row,
            "nextStartRow": offset,
            "rowsReturned": len(rows),
            "limitReached": not exhausted,
        },
    }


def flatten_rows(response: dict, dimensions: list[str]) -> list[dict]:
    return [
        {
            **dict(zip(dimensions, row.get("keys", []))),
            **{k: v for k, v in row.items() if k != "keys"},
        }
        for row in response.get("rows", [])
    ]
