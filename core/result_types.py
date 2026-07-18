"""Typed schema for the inspection result.

The inspection result is a nested dict accessed by string keys across the
pipeline, reporter, GUI and batch layers (e.g. ``result["execution"]["gpu"]
["metrics"]``). These ``TypedDict`` definitions document that contract in one
place so editors and type checkers can catch typos, and :mod:`tests` can assert
that real pipeline output still conforms to it.

They are runtime-erased annotations: importing or annotating with them changes
no behaviour, so they are safe to layer onto the existing dict-based result.
"""

from __future__ import annotations

from typing import Any, TypedDict


class InspectionSummary(TypedDict):
    tile_count: int
    ng_count: int
    defect_count: int
    detector_ng_counts: dict[str, int]


class ResidentImageStatus(TypedDict):
    active: bool
    generation: int
    shape: list[int]


class DetectorExecutionStatus(TypedDict):
    requested: bool
    active: bool
    backend: str
    fallback_reason: str


class GpuExecution(TypedDict):
    mode: str
    resident_image: ResidentImageStatus
    tiling: Any
    display_requested: bool
    detectors: dict[str, DetectorExecutionStatus]
    metrics: dict[str, Any]


class ExecutionBlock(TypedDict):
    gpu: GpuExecution
    performance: dict[str, Any]


class InspectionResult(TypedDict):
    image_name: str
    recipe_name: str
    machine_id: Any
    product_id: Any
    recipe_version: Any
    provenance: dict[str, Any]
    final_result: str
    summary: InspectionSummary
    tiles: list[dict[str, Any]]
    outputs: dict[str, Any]
    duration_sec: float
    execution: ExecutionBlock


def required_keys(typed_dict: type) -> frozenset[str]:
    """Return the declared keys of a TypedDict for structural contract checks."""
    return frozenset(getattr(typed_dict, "__annotations__", {}))
