"""Scientific conventions and degenerate-data checks for transparent methods."""
import json
import unittest

import numpy as np

from tma_app.numerics import analyze, apply_transform, process_signal


class AnalysisTests(unittest.TestCase):
    def test_signal_max_negative_values_ties_and_inclusive_samples(self):
        result = analyze([0, 1, 2, 3, 4], [50, -5, -2, -2, 60], "signal_max", 0.5, 3.5)
        self.assertEqual((result["max_x"], result["max_y"], result["value"]), (2, -2, -2))
        self.assertEqual((result["start_x"], result["start_y"], result["stop_x"], result["stop_y"]), (1, -5, 3, -2))
        self.assertEqual(result["selection"], "sampled inclusive bounds")
        self.assertEqual(result["vendor_equivalence"], "unverified")
        self.assertEqual(result["method"], "signal_max")
        self.assertNotIn("peak_x", result)
        json.dumps(result, allow_nan=False)

    def test_signal_max_allows_hold_and_contiguous_turns(self):
        result = analyze([3, 2, 2, 1, 2, 3], [-4, -1, -1, -7, -2, -3], "signal_max", 1, 3)
        self.assertEqual((result["max_x"], result["max_y"]), (2, -1))
        self.assertEqual(result["direction"], "nonmonotonic")
        constant = analyze([2, 2, 2], [-3, -2, -1], "signal_max", 1, 3)
        self.assertEqual(constant["direction"], "constant")
        self.assertEqual(constant["value"], -1)
        # Range arithmetic must not overflow merely to compare finite X values.
        extreme = analyze([-1e308, 1e308], [-1e308, 1e308], "signal_max", -1e308, 1e308)
        self.assertEqual(extreme["value"], 1e308)

    def test_signal_change_signed_cooling_and_two_point_selection(self):
        result = analyze([5, 4, 3, 2, 1], [20, 10, 8, 3, -50], "signal_change", 1.5, 4.5)
        self.assertEqual((result["start_x"], result["start_y"]), (4, 10))
        self.assertEqual((result["stop_x"], result["stop_y"]), (2, 3))
        self.assertEqual((result["value"], result["change"]), (-7, -7))
        self.assertEqual(result["direction"], "decreasing")
        pair = analyze([0, 1], [-4, -1], "signal_change", 0, 1)
        self.assertEqual(pair["value"], 3)
        self.assertEqual(pair["selection"], "sampled inclusive bounds")
        self.assertEqual(pair["vendor_equivalence"], "unverified")
        json.dumps(result, allow_nan=False)

    def test_signal_change_allows_contiguous_holds_and_reversals(self):
        for x, expected_direction in (([1, 2, 2, 3], "increasing"),
                                      ([3, 2, 2, 1], "decreasing"),
                                      ([2, 2, 2, 2], "constant")):
            with self.subTest(x=x):
                result = analyze(x, [4, 10, -20, 7], "signal_change", 1, 3)
                self.assertEqual(result["value"], 3)
                self.assertEqual(result["direction"], expected_direction)
        for x in ([1, 2, 3, 2, 1], [1, 2, 2, 1], [3, 1, 2]):
            with self.subTest(x=x):
                result = analyze(x, np.arange(len(x)), "signal_change", 1, 3)
                self.assertEqual(result["change"], len(x) - 1)
                self.assertEqual(result["direction"], "nonmonotonic")
        hold = analyze([2, 2, 2], [1, 5, 8], "signal_change", 2, 2)
        self.assertEqual(hold["change"], 7)

    def test_signal_methods_reject_disjoint_cycles_nonfinite_and_overflow(self):
        for kind in ("signal_max", "signal_change"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "采集片段"):
                analyze([0, 1, 2, 3, 2, 1, 0], [0, 1, 2, 3, 4, 5, 6], kind, 0, 2)
            for y in ([0, np.nan], [np.inf, 0]):
                with self.subTest(kind=kind, y=y), self.assertRaises(ValueError):
                    analyze([0, 1], y, kind, 0, 1)
        # Finite operands may still produce an infinite signed change.
        with self.assertRaisesRegex(ValueError, "有限数值"):
            analyze([0, 1], [-1e308, 1e308], "signal_change", 0, 1)
        # Existing APIs preserve their strictly monotonic validation.
        for kind in ("peak", "change"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "重复"):
                analyze([1, 2, 2, 3], [0, 1, 2, 3], kind, 1, 3)

    def test_linear_regression_and_cte_units(self):
        x = np.linspace(20, 120, 101)
        y = 0.2 * x + 3
        fitted = analyze(x, y, "slope", 20, 120)
        self.assertAlmostEqual(fitted["slope"], 0.2)
        self.assertAlmostEqual(fitted["intercept"], 3)
        self.assertAlmostEqual(fitted["r2"], 1)
        # 0.2 um/K divided by 10 mm is 20 ppm/K.
        cte = analyze(x, y, "cte", 20, 120, reference_length_mm=10)
        self.assertAlmostEqual(cte["cte_ppm_per_k"], 20)
        self.assertTrue(all(isinstance(v, (float, str)) for v in cte.values()))
        json.dumps(cte, allow_nan=False)

    def test_endpoint_baseline_area_and_cooling_sign(self):
        x = np.array([0., 1., 2.])
        y = np.array([5., 8., 7.])  # Baseline [5, 6, 7], area = 2.
        self.assertAlmostEqual(analyze(x, y, "integral", 0, 2)["integral"], 2)
        reverse = analyze(x[::-1], y[::-1], "integral", 0, 2)
        self.assertAlmostEqual(reverse["integral"], -2)
        self.assertEqual(reverse["direction"], "decreasing")
        self.assertAlmostEqual(analyze(x[::-1], y[::-1], "slope", 0, 2)["slope"], 1)

    def test_peak_and_change_follow_samples_in_acquisition_order(self):
        result = analyze([4, 3, 2, 1], [2, 7, 7, -1], "peak", 1, 4)
        self.assertEqual((result["max_x"], result["max_y"]), (3, 7))
        self.assertEqual((result["min_x"], result["min_y"]), (1, -1))
        delta = analyze([4, 3, 2, 1], [2, 7, 7, -1], "change", 1, 4)
        self.assertEqual(delta["change"], -3)

    def test_inclusive_interval_no_extrapolation(self):
        result = analyze([0, 1, 2, 3, 4], [0, 1, 4, 9, 16], "change", 0.5, 3.5)
        self.assertEqual((result["x_start"], result["x_end"], result["points"]), (1, 3, 3))
        self.assertEqual(result["change"], 8)

    def test_onset_known_piecewise_lines(self):
        x = np.linspace(0, 10, 101)
        y = 0.1 * x + np.maximum(x - 4, 0) * 2
        result = analyze(x, y, "onset", 0, 10)
        self.assertAlmostEqual(result["onset_x"], 4, places=10)
        self.assertAlmostEqual(result["onset_y"], 0.4, places=10)
        self.assertIn("20%", result["algorithm"])

    def test_invalid_analysis_inputs(self):
        cases = [([0, 1, 1], [1, 2, 3], 0, 2),
                 ([0, 2, 1], [1, 2, 3], 0, 2),
                 ([0, 1, 2], [1, np.nan, 3], 0, 2),
                 (np.array([0 + 1j, 1]), [1, 2], 0, 2),
                 ([0, 1], [1], 0, 2),
                 ([[0, 1]], [[1, 2]], 0, 2),
                 ([0, 1], [1, 2], 1, 1),
                 ([0, 1], [1, 2], 0, np.inf),
                 ([0, 1], [1, 2], 3, 4),
                 # Disjoint acquisitions may otherwise appear monotonic after filtering.
                 ([0, 1, 5, 2, 3], [0, 1, 5, 2, 3], 0, 3)]
        for x, y, lo, hi in cases:
            with self.subTest(x=x, lo=lo, hi=hi), self.assertRaises(ValueError):
                analyze(x, y, "slope", lo, hi)

    def test_cte_requires_positive_explicit_length(self):
        for length in (None, 0, -1, np.nan, np.inf):
            with self.subTest(length=length), self.assertRaises(ValueError):
                analyze([0, 1], [0, 1], "cte", 0, 1, length)

    def test_degenerate_onset_and_constant_regression(self):
        x = np.linspace(0, 10, 101)
        self.assertEqual(analyze(x, np.ones_like(x), "slope", 0, 10)["r2"], 1)
        for y in (np.ones_like(x), 2 * x + 5):
            with self.assertRaisesRegex(ValueError, "平行|常量"):
                analyze(x, y, "onset", 0, 10)
        with self.assertRaisesRegex(ValueError, "10"):
            analyze([0, 1, 2], [0, 1, 3], "onset", 0, 2)
        with self.assertRaisesRegex(ValueError, "不在"):
            analyze(np.arange(10.), [7, 9, 1, -6, -10, -4, -5, 9, 1, -7], "onset", 0, 9)


class ProcessingTests(unittest.TestCase):
    def test_nonuniform_derivative_and_cooling(self):
        x = np.array([0., .4, 1.5, 3., 5.])
        expected = 2 * x
        np.testing.assert_allclose(process_signal(x, x*x, "derivative"), expected, atol=1e-12)
        np.testing.assert_allclose(process_signal(x[::-1], (x*x)[::-1], "derivative"), expected[::-1], atol=1e-12)
        for xs in ([0, 1, 1], [0, 2, 1]):
            with self.assertRaises(ValueError):
                process_signal(xs, [0, 1, 2], "derivative")

    def test_smooth_preserves_quadratic_and_inputs(self):
        x = np.arange(11.)
        y = x*x + 2*x + 1
        original = y.copy()
        result = process_signal(x, y, "smooth", 5)
        np.testing.assert_allclose(result, original, atol=1e-10)
        np.testing.assert_array_equal(y, original)
        self.assertFalse(np.shares_memory(y, result))
        for window in (0, 2, 4, 5.5, 13, np.inf):
            with self.subTest(window=window), self.assertRaises(ValueError):
                process_signal(x, y, "smooth", window)

    def test_normalize_and_transforms(self):
        x, y = np.array([0., 1., 2.]), np.array([2., 3., 4.])
        np.testing.assert_allclose(process_signal(x, y, "normalize"), [100, 150, 200])
        with self.assertRaises(ValueError):
            process_signal(x, [0, 1, 2], "normalize")
        tx, ty = apply_transform(x, y, x_shift=2, y_scale=-3, y_offset=1)
        np.testing.assert_array_equal(tx, [2, 3, 4])
        np.testing.assert_array_equal(ty, [-5, -8, -11])
        np.testing.assert_array_equal(x, [0, 1, 2])
        np.testing.assert_array_equal(y, [2, 3, 4])
        with self.assertRaises(ValueError):
            apply_transform(x, y, y_scale=np.inf)
        with self.assertRaises(ValueError):
            apply_transform(x, y, y_scale=1e308)


if __name__ == "__main__":
    unittest.main()
