"""Portable sessions preserve measured data and reject unsafe array payloads."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from tma_app.reader import Dataset, Signal, read_dataset
from tma_app.workspace import Curve, default_plot_options, load_session, save_session, validate_plot_options


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "样品.002"
        self.source.write_bytes(b"immutable source instrument bytes\x00\xff")
        self.values = np.array([[0., 25., .2], [1., 30., .8], [2., 35., 1.6]])
        self.dataset = Dataset(
            self.source,
            [Signal("Time", "min"), Signal("Temperature", "°C"), Signal("Dimension Change", "µm")],
            self.values.copy(), {"Sample": ["样品", "第二行"], "_raw_header": ["original\r\nheader"]},
            ["数据可能截断：保留有效记录"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.path = self.root / "分析.tmasession"

    def save_default(self):
        save_session(self.path, [Curve(self.dataset)], "temperature", [])

    def rewrite(self, change_document=None, replacements=None):
        """Rewrite our own small fixture; no filesystem extraction is involved."""
        with zipfile.ZipFile(self.path) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        if change_document:
            doc = json.loads(members["session.json"])
            change_document(doc)
            members["session.json"] = json.dumps(doc).encode("utf-8")
        members.update(replacements or {})
        with zipfile.ZipFile(self.path, "w") as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)

    @staticmethod
    def npy(array, *, pickle=False):
        stream = BytesIO()
        np.save(stream, array, allow_pickle=pickle)
        return stream.getvalue()

    def test_complete_round_trip_preserves_order_arrays_state_and_results(self):
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        first = Curve(self.dataset, y_index=2, axis=3, color="#123456", visible=False,
                      width=2.75, style="-.", x_shift=4.5, scale=-2., offset=7.,
                      working=np.array([2., 4., 8.]), operations=["smooth:5", "derivative:Temperature (°C)"])
        second = Curve(self.dataset, y_index=1, axis=1, color="#abcdef", style=":")
        results = [{"file": self.source.name, "sha256": original_hash, "kind": "slope",
                    "domain": "time", "lo": 0., "hi": 2., "signal": first.result_label,
                    "axis": 4, "operations": list(first.operations),
                    "transform": {"x_shift": 4.5, "scale": -2., "offset": 7.},
                    "reference_length_mm": None,
                    "values": {"slope": 3., "intercept": -2., "r2": .9}}]
        expected_xy = first.xy("time")
        save_session(self.path, [first, second], "time", results)
        restored, domain, restored_results = load_session(self.path)
        self.assertEqual(domain, "time")
        self.assertEqual(restored_results, results)
        self.assertEqual(len(restored), 2)
        self.assertEqual([c.y_index for c in restored], [2, 1])
        for before, after in zip([first, second], restored):
            self.assertEqual(after.dataset.path, before.dataset.path)
            self.assertEqual(after.dataset.sha256, before.dataset.sha256)
            self.assertEqual(after.dataset.metadata, before.dataset.metadata)
            self.assertEqual(after.dataset.warnings, before.dataset.warnings)
            self.assertEqual(after.dataset.signals, before.dataset.signals)
            np.testing.assert_array_equal(after.dataset.values, before.dataset.values)
            for key in ("y_index", "axis", "color", "visible", "width", "style", "x_shift", "scale", "offset", "operations"):
                self.assertEqual(getattr(after, key), getattr(before, key), key)
        np.testing.assert_array_equal(restored[0].working, first.working)
        self.assertIsNone(restored[1].working)
        for actual, expected in zip(restored[0].xy("time"), expected_xy):
            np.testing.assert_array_equal(actual, expected)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)
        np.testing.assert_array_equal(self.dataset.values, self.values)

    def test_plot_and_curve_presentation_settings_round_trip(self):
        curve = Curve(self.dataset, marker="D", legend_text="实验 2 / 升温", show_legend=False,
                      overlay_enabled=False, style="None")
        settings = {"title": "TMA 比较", "x_label": "温度 / °C", "y_labels": ["尺寸", "力", "流量", "导数"],
                    "legend": True, "legend_location": "lower left", "grid_x": True, "grid_y": False,
                    "grid_minor": True, "auto_x": False, "auto_y": [False, True, False, True],
                    "x_limits": [-40., 200.], "y_limits": [[-1., 5.], None, [0., 10.], None]}
        documents = {"__overlay__": settings, str(self.source): {"title": "原始数据", "legend": False}}
        save_session(self.path, [curve], "temperature", [], plot_options=documents)
        curves, domain, results, loaded = load_session(self.path, include_plot_options=True)
        self.assertEqual((domain, results), ("temperature", []))
        self.assertEqual(loaded["__overlay__"], validate_plot_options(settings))
        self.assertEqual(loaded[str(self.source)], validate_plot_options(documents[str(self.source)]))
        for key in ("marker", "legend_text", "show_legend", "overlay_enabled", "style"):
            self.assertEqual(getattr(curves[0], key), getattr(curve, key))
        self.assertEqual(len(load_session(self.path)), 3)

    def test_legacy_session_supplies_optional_defaults(self):
        self.save_default()
        def legacy(doc):
            doc.pop("plot_options")
            for entry in doc["curves"]:
                for key in ("marker", "legend_text", "show_legend", "overlay_enabled", "display_filename", "show_legend_text"):
                    entry.pop(key)
        self.rewrite(legacy)
        curves, _, _, options = load_session(self.path, include_plot_options=True)
        self.assertEqual((curves[0].marker, curves[0].legend_text, curves[0].show_legend, curves[0].overlay_enabled),
                         ("", self.source.name, True, True))
        self.assertEqual(options, {})

    def test_default_plot_options_are_independent_and_unknown_fields_ignored(self):
        first = default_plot_options()
        first["auto_y"][0] = False
        first["y_labels"][0] = "changed"
        other = default_plot_options()
        self.assertTrue(other["auto_y"][0])
        self.assertEqual(other["y_labels"][0], "")
        self.assertFalse(other["grid_x"])
        self.assertFalse(other["grid_y"])
        source = {"title": "保存标题", "future_setting": {"irrelevant": True}, "y_limits": [[0, 1], None, None, None]}
        validated = validate_plot_options(source)
        validated["y_limits"][0][0] = -10
        self.assertEqual(source["y_limits"][0][0], 0)
        self.assertNotIn("future_setting", validated)

    def test_curve_presentation_state_is_strict_on_save_and_load(self):
        invalid = [("marker", "*"), ("marker", None), ("legend_text", 1), ("legend_text", "x" * 4097),
                   ("show_legend", 1), ("overlay_enabled", "false"), ("visible", None),
                   ("color", "red"), ("color", "#fff"), ("color", "#ghijkl"),
                   ("width", True), ("scale", "2"), ("operations", [None])]
        for key, value in invalid:
            with self.subTest(key=key, value=str(value)[:40]):
                curve = Curve(self.dataset)
                setattr(curve, key, value)
                with self.assertRaises(ValueError):
                    save_session(self.path, [curve], "temperature", [])
                self.save_default()
                self.rewrite(lambda doc: doc["curves"][0].update({key: value}))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_all_supported_markers_and_legend_locations(self):
        for marker in ("", "o", "s", "^", "v", "+", "x", ".", "D"):
            with self.subTest(marker=marker):
                save_session(self.path, [Curve(self.dataset, marker=marker)], "temperature", [])
                self.assertEqual(load_session(self.path)[0][0].marker, marker)
        for location in ("best", "upper right", "upper left", "lower right", "lower left"):
            self.assertEqual(validate_plot_options({"legend_location": location})["legend_location"], location)
        for legend in (None, True, False):
            self.assertIs(validate_plot_options({"legend": legend})["legend"], legend)

    def test_invalid_plot_settings_are_rejected_on_save_and_load(self):
        invalid = [("title", 1), ("x_label", "x" * 4097), ("y_labels", [""] * 3),
                   ("y_labels", ["", "", "", None]), ("legend", 1), ("legend_location", "center"),
                   ("grid_x", 1), ("grid_y", "false"), ("grid_minor", None), ("auto_x", 0),
                   ("auto_y", [True] * 3), ("auto_y", [True, True, True, 0]),
                   ("x_limits", [2, 1]), ("x_limits", [1, 1]), ("x_limits", [True, 2]),
                   ("x_limits", [0, float("inf")]), ("x_limits", [0, "2"]),
                   ("y_limits", [None] * 3), ("y_limits", [None, None, None, [2, 1]])]
        for key, value in invalid:
            with self.subTest(key=key, value=str(value)[:40]):
                with self.assertRaises(ValueError):
                    validate_plot_options({key: value})
                with self.assertRaises(ValueError):
                    save_session(self.path, [Curve(self.dataset)], "temperature", [],
                                 plot_options={"__overlay__": {key: value}})
                self.save_default()
                self.rewrite(lambda doc: doc.update(plot_options={"__overlay__": {key: value}}))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_plot_document_mapping_rejects_invalid_known_state(self):
        for options in ([], {"": {}}, {"__overlay__": []}, {"a": None}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    save_session(self.path, [Curve(self.dataset)], "time", [], plot_options=options)

    def test_invalid_plot_save_keeps_previous_session(self):
        self.save_default()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_session(self.path, [Curve(self.dataset)], "temperature", [],
                         plot_options={"__overlay__": {"x_limits": [0., float("nan")]}})
        self.assertEqual(self.path.read_bytes(), before)

    def test_session_recovers_embedded_data_when_original_file_is_missing(self):
        self.save_default()
        self.source.unlink()
        curves, domain, _ = load_session(self.path)
        self.assertFalse(curves[0].dataset.path.exists())
        np.testing.assert_array_equal(curves[0].dataset.values, self.values)
        x, y = curves[0].xy(domain)
        np.testing.assert_array_equal(x, [25, 30, 35])
        np.testing.assert_array_equal(y, [.2, .8, 1.6])

    def test_processing_and_undo_do_not_mutate_measured_array(self):
        curve = Curve(self.dataset)
        curve.checkpoint()
        curve.working = np.array([100., 400., 800.])
        curve.operations.append("normalize")
        curve.checkpoint()
        curve.working[0] = 999.
        curve.operations.append("smooth:3")
        curve.undo()
        np.testing.assert_array_equal(curve.working, [100, 400, 800])
        self.assertEqual(curve.operations, ["normalize"])
        curve.undo()
        self.assertIsNone(curve.working)
        self.assertEqual(curve.operations, [])
        np.testing.assert_array_equal(self.dataset.values, self.values)

    def test_reset_undo_restores_transforms_and_processing_together(self):
        curve = Curve(self.dataset, x_shift=4., scale=2., offset=-5.,
                      working=np.array([100., 200., 300.]), operations=["normalize"])
        expected_x, expected_y = curve.xy()
        curve.checkpoint()
        curve.working = None
        curve.operations = []
        curve.x_shift, curve.scale, curve.offset = 0., 1., 0.
        curve.undo()
        self.assertEqual((curve.x_shift, curve.scale, curve.offset), (4., 2., -5.))
        self.assertEqual(curve.operations, ["normalize"])
        x, y = curve.xy()
        np.testing.assert_array_equal(x, expected_x)
        np.testing.assert_array_equal(y, expected_y)

    def test_object_array_is_rejected_without_unpickling(self):
        for member, array in (("0-data.npy", np.array([[object()]], dtype=object)),
                              ("0-working.npy", np.array([object(), object(), object()], dtype=object))):
            with self.subTest(member=member):
                self.save_default()
                self.rewrite(lambda doc: doc["curves"][0].update(has_working=member.endswith("working.npy")),
                             {member: self.npy(array, pickle=True)})
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_invalid_signal_and_axis_indices_are_rejected(self):
        for key, value in (("y_index", -1), ("y_index", 3), ("axis", -1), ("axis", 4),
                           ("y_index", 1.5), ("axis", .5), ("y_index", True), ("axis", False)):
            with self.subTest(key=key, value=value):
                self.save_default()
                self.rewrite(lambda doc: doc["curves"][0].update({key: value}))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_bad_dimensions_and_nonfinite_arrays_are_rejected(self):
        for bad in (self.values[:, :2], self.values.ravel(), self.values[:1],
                    np.array([[0., 25., np.nan], [1., 30., 1.]]), self.values.astype(complex) + 1j):
            with self.subTest(shape=bad.shape, dtype=bad.dtype):
                self.save_default()
                self.rewrite(replacements={"0-data.npy": self.npy(bad)})
                with self.assertRaises(ValueError):
                    load_session(self.path)
        for bad in (np.array([1., 2.]), np.array([[1., 2., 3.]]), np.array([1., np.inf, 3.]),
                    np.array([1 + 1j, 2, 3])):
            with self.subTest(working=bad):
                self.save_default()
                self.rewrite(lambda doc: doc["curves"][0].update(has_working=True),
                             {"0-working.npy": self.npy(bad)})
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_invalid_domain_and_version_are_rejected(self):
        for change in ({"domain": "pressure"}, {"version": 999}, {"format": "other"}):
            with self.subTest(change=change):
                self.save_default()
                self.rewrite(lambda doc: doc.update(change))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_invalid_width_style_and_nonfinite_transforms_are_rejected(self):
        for key, value in (("width", 0), ("width", -1), ("width", float("nan")),
                           ("style", "unknown"), ("x_shift", float("inf")),
                           ("scale", float("nan")), ("offset", -float("inf"))):
            with self.subTest(key=key, value=value):
                self.save_default()
                self.rewrite(lambda doc: doc["curves"][0].update({key: value}))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_malformed_analysis_result_collection_is_rejected(self):
        for results in ({}, "results", [None], [{"values": {}}]):
            with self.subTest(results=results):
                self.save_default()
                self.rewrite(lambda doc: doc.update(results=results))
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_failed_save_preserves_previous_session_and_cleans_temporary_file(self):
        self.save_default()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_session(self.path, [Curve(self.dataset)], "temperature", [{"value": np.nan}])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".tma-*.tmp")), [])

    @unittest.skipUnless(Path(r"C:\Users\Administrator\Desktop\cga\1.001").is_file(), "reference instrument file unavailable")
    def test_real_instrument_file_round_trip_keeps_source_hash(self):
        source = Path(r"C:\Users\Administrator\Desktop\cga\1.001")
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        dataset = read_dataset(source)
        save_session(self.path, [Curve(dataset)], "temperature", [])
        curves, _, _ = load_session(self.path)
        self.assertEqual(curves[0].dataset.sha256, original_hash)
        np.testing.assert_array_equal(curves[0].dataset.values, dataset.values)
        self.assertEqual(curves[0].dataset.metadata, dataset.metadata)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)


if __name__ == "__main__":
    unittest.main()
