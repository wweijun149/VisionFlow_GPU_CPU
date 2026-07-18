"""Verification for the P9 optimization backlog.

Covers behaviour-preserving guarantees (serial vs parallel tile inspection are
numerically identical) and the new opt-in knobs: recipe caching, batch worker /
GC policy, reporter PNG params, and per-detector debug image export.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import core.recipe_manager as recipe_manager
from core.batch_processor import BatchInspectionProcessor
from core.pipeline import AOIPipeline
from core.recipe_manager import RecipeManager
from core.reporter import Reporter
from core.result_types import (
    ExecutionBlock,
    GpuExecution,
    InspectionResult,
    InspectionSummary,
    required_keys,
)

ROOT = Path(__file__).resolve().parents[1]
CIRCLE_RECIPE = ROOT / "recipes" / "PRODUCT_A_CIRCLE_401_1_AOI_01.yaml"
NEGATIVE_RECIPE = ROOT / "recipes" / "PRODUCT_A_NEGATIVE_401_AOI_01.yaml"

NO_FILE_OUTPUT = {
    "save_overlay": False,
    "save_ng_tiles": False,
    "save_csv": False,
    "save_matrix_csv": False,
    "save_json": False,
}


def multi_tile_image() -> np.ndarray:
    """White field large enough to force a grid of tiles, with a few NG circles."""
    image = np.full((1100, 1100, 3), 255, np.uint8)
    for cx, cy in ((256, 256), (820, 300), (540, 900)):
        cv2.circle(image, (cx, cy), 16, (0, 0, 0), -1)
    return image


def normalized_tiles(result: dict) -> list:
    """A stable view of the inspection independent of timing/ordering noise."""
    rows = []
    for tile_result in result["tiles"]:
        tile = tile_result["tile"]
        detectors = []
        for detector in tile_result["detectors"]:
            defects = sorted(
                (
                    (
                        defect.get("type"),
                        tuple(defect.get("bbox_global", [])),
                        round(float(defect.get("area", 0.0)), 3),
                    )
                    for defect in detector.get("defects", [])
                ),
            )
            detectors.append((detector["detector_id"], detector["pass"], tuple(defects)))
        rows.append(((tile["x"], tile["y"], tile["row"], tile["col"]), tuple(detectors)))
    return sorted(rows)


class RecipeCacheTests(unittest.TestCase):
    def setUp(self):
        recipe_manager._RECIPE_CACHE.clear()

    def tearDown(self):
        recipe_manager._RECIPE_CACHE.clear()

    def test_load_returns_independent_copies(self):
        manager = RecipeManager()
        first = manager.load(NEGATIVE_RECIPE)
        second = manager.load(NEGATIVE_RECIPE)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["output"]["mutated"] = True
        third = manager.load(NEGATIVE_RECIPE)
        self.assertNotIn("mutated", third["output"])

    def test_cache_avoids_reparsing_until_mtime_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recipe.yaml"
            path.write_bytes(NEGATIVE_RECIPE.read_bytes())
            manager = RecipeManager()

            with mock.patch("core.recipe_manager.yaml.safe_load", wraps=recipe_manager.yaml.safe_load) as spy:
                manager.load(path)
                manager.load(path)
                self.assertEqual(spy.call_count, 1)  # second load served from cache

                # Bump mtime to force cache invalidation on the next load.
                os.utime(path, (time.time() + 5, time.time() + 5))
                manager.load(path)
                self.assertEqual(spy.call_count, 2)  # reparsed after mtime change


class TileParallelEquivalenceTests(unittest.TestCase):
    def setUp(self):
        recipe_manager._RECIPE_CACHE.clear()

    def _run(self, workers: str | None) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "input.png"
            ok, buf = cv2.imencode(".png", multi_tile_image())
            image_path.write_bytes(buf.tobytes())
            env = {"AOI_TILE_WORKERS": workers} if workers is not None else {}
            with mock.patch.dict(os.environ, env, clear=False):
                if workers is None:
                    os.environ.pop("AOI_TILE_WORKERS", None)
                return AOIPipeline(
                    CIRCLE_RECIPE, root / "out", output_overrides=NO_FILE_OUTPUT
                ).run(image_path)

    def test_parallel_matches_serial(self):
        serial = self._run(None)
        parallel = self._run("4")
        self.assertGreater(len(serial["tiles"]), 1)  # multiple tiles so fan-out engages
        self.assertEqual(serial["final_result"], parallel["final_result"])
        self.assertEqual(serial["summary"], parallel["summary"])
        self.assertEqual(normalized_tiles(serial), normalized_tiles(parallel))


class WorkerAndGcPolicyTests(unittest.TestCase):
    def _processor(self, **env) -> BatchInspectionProcessor:
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("AOI_BATCH_WORKERS", "AOI_BATCH_GC_INTERVAL"):
                if key not in env:
                    os.environ.pop(key, None)
            return BatchInspectionProcessor(ROOT, NEGATIVE_RECIPE, ROOT / "out")

    def test_worker_count_scales_beyond_four_but_is_bounded(self):
        proc = self._processor()
        with mock.patch("core.batch_processor.os.cpu_count", return_value=16):
            self.assertEqual(proc._worker_count(100), 8)  # new cap is 8, not 4
            self.assertEqual(proc._worker_count(3), 3)  # never exceeds image count

    def test_env_override_and_explicit_max_workers(self):
        proc = self._processor()
        with mock.patch.dict(os.environ, {"AOI_BATCH_WORKERS": "2"}, clear=False):
            self.assertEqual(proc._worker_count(100), 2)
        proc = BatchInspectionProcessor(ROOT, NEGATIVE_RECIPE, ROOT / "out", max_workers=3)
        self.assertEqual(proc._worker_count(100), 3)

    def test_opencv_thread_budget_restores_previous_setting(self):
        proc = self._processor()
        previous = cv2.getNumThreads()
        with proc._opencv_thread_budget(4):
            pass
        self.assertEqual(cv2.getNumThreads(), previous)

    def test_gc_interval_env_and_default(self):
        self.assertEqual(self._processor()._gc_interval, 8)
        self.assertEqual(self._processor(AOI_BATCH_GC_INTERVAL="0")._gc_interval, 0)
        self.assertEqual(self._processor(AOI_BATCH_GC_INTERVAL="3")._gc_interval, 3)

    def test_maybe_collect_only_fires_on_interval(self):
        proc = self._processor(AOI_BATCH_GC_INTERVAL="3")
        with mock.patch("core.batch_processor.gc.collect") as collect:
            for _ in range(6):
                proc._maybe_collect()
            self.assertEqual(collect.call_count, 2)  # fired at 3 and 6


class ReporterPngParamsTests(unittest.TestCase):
    def test_absent_config_keeps_opencv_default(self):
        self.assertEqual(Reporter._resolve_png_params({}), [])

    def test_compression_level_is_clamped(self):
        self.assertEqual(Reporter._resolve_png_params({"png_compression": 9})[1], 9)
        self.assertEqual(Reporter._resolve_png_params({"png_compression": 42})[1], 9)
        self.assertEqual(Reporter._resolve_png_params({"png_compression": -1})[1], 0)


class DebugImageExportTests(unittest.TestCase):
    def setUp(self):
        recipe_manager._RECIPE_CACHE.clear()

    def test_debug_images_written_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "input.png"
            ok, buf = cv2.imencode(".png", multi_tile_image())
            image_path.write_bytes(buf.tobytes())
            overrides = {**NO_FILE_OUTPUT, "save_debug_images": True}
            result = AOIPipeline(
                CIRCLE_RECIPE, root / "out", output_overrides=overrides
            ).run(image_path)
            debug_paths = result["outputs"].get("debug_images", [])
            self.assertTrue(debug_paths, "debug images should be exported when enabled")
            for path in debug_paths:
                self.assertTrue(Path(path).exists())
            # Runtime-only debug payload must never leak into serializable tiles.
            for tile_result in result["tiles"]:
                self.assertNotIn("_debug_images", tile_result)


class ResultSchemaContractTests(unittest.TestCase):
    def setUp(self):
        recipe_manager._RECIPE_CACHE.clear()

    def test_pipeline_result_conforms_to_typed_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "input.png"
            ok, buf = cv2.imencode(".png", multi_tile_image())
            image_path.write_bytes(buf.tobytes())
            result = AOIPipeline(
                CIRCLE_RECIPE, root / "out", output_overrides=NO_FILE_OUTPUT
            ).run(image_path)

        self.assertLessEqual(required_keys(InspectionResult), set(result))
        self.assertLessEqual(required_keys(InspectionSummary), set(result["summary"]))
        self.assertLessEqual(required_keys(ExecutionBlock), set(result["execution"]))
        self.assertLessEqual(required_keys(GpuExecution), set(result["execution"]["gpu"]))


if __name__ == "__main__":
    unittest.main()
