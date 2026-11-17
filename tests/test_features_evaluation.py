"""Step 7 leakage-safe features and evaluation tests."""

from __future__ import annotations

import math
import unittest

from forecast.evaluate import leave_one_link_out_splits, rolling_origin_folds
from forecast.features import FeatureRow, Observation, build_features
from forecast.models import MODEL_NAMES, predict


class FeatureBuilderTests(unittest.TestCase):
    def test_feature_at_t_uses_observations_through_t_only(self) -> None:
        observations = [
            Observation(
                timestamp=float(index * 5),
                router="r1",
                interface="eth1",
                link="r1-r2",
                value=float(index),
            )
            for index in range(6)
        ]

        rows = build_features(
            observations,
            horizon_steps=1,
            lag_steps=(1,),
            rolling_window=3,
            seasonal_period=2,
            expected_step_seconds=5,
        )

        first = rows[0]
        self.assertEqual(first.timestamp, 10.0)
        self.assertEqual(first.features["current"], 2.0)
        self.assertEqual(first.features["lag_1"], 1.0)
        self.assertEqual(first.features["rolling_mean_3"], 1.0)
        self.assertEqual(first.features["seasonal_lag_2"], 0.0)
        self.assertEqual(first.target, 3.0)
        self.assertNotIn(first.target, first.features.values())

    def test_gap_and_insufficient_history_produce_no_feature_rows(self) -> None:
        observations = [
            Observation(
                timestamp=timestamp,
                router="r1",
                interface="eth1",
                link="r1-r2",
                value=value,
            )
            for timestamp, value in ((0.0, 1.0), (5.0, 2.0), (15.0, 3.0), (20.0, 4.0))
        ]

        rows = build_features(
            observations,
            horizon_steps=1,
            lag_steps=(1,),
            rolling_window=3,
            seasonal_period=2,
            expected_step_seconds=5,
        )

        self.assertEqual(rows, [])


class EvaluationSplitTests(unittest.TestCase):
    def test_rolling_folds_keep_training_strictly_before_validation(self) -> None:
        folds, skipped = rolling_origin_folds(
            timestamps=[0.0, 5.0, 10.0, 15.0, 20.0, 25.0],
            initial_train_timestamps=3,
            validation_timestamps=2,
            step_timestamps=1,
        )

        self.assertEqual(skipped, [])
        self.assertEqual(len(folds), 2)
        self.assertLess(max(folds[0].train_timestamps), min(folds[0].validation_timestamps))

    def test_rolling_folds_report_insufficient_history(self) -> None:
        folds, skipped = rolling_origin_folds(
            timestamps=[0.0, 5.0, 10.0],
            initial_train_timestamps=3,
            validation_timestamps=2,
            step_timestamps=1,
        )

        self.assertEqual(folds, [])
        self.assertEqual(skipped, ["insufficient timestamps for one validation fold"])

    def test_link_transfer_requires_more_than_one_link(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two links"):
            leave_one_link_out_splits(["r1-r2", "r1-r2"])


class ModelTests(unittest.TestCase):
    def test_every_required_model_predicts_one_value_per_test_row(self) -> None:
        rows = [
            FeatureRow(
                timestamp=float(index),
                router="r1",
                interface="eth1",
                link="r1-r2",
                features={
                    "current": index / 100,
                    "lag_1": max(0, index - 1) / 100,
                    "rolling_mean_3": max(0, index - 1) / 100,
                    "seasonal_lag_2": max(0, index - 2) / 100,
                },
                target=(index + 1) / 100,
            )
            for index in range(16)
        ]

        for model in MODEL_NAMES:
            predictions = predict(model, train_rows=rows[:12], test_rows=rows[12:])

            self.assertEqual(len(predictions), 4)
            self.assertTrue(all(math.isfinite(value) for value in predictions))

    def test_all_models_bound_predictions_to_utilization_ratio(self) -> None:
        train_rows = [
            FeatureRow(
                timestamp=float(index),
                router="r1",
                interface="eth1",
                link="r1-r2",
                features={
                    "current": float(index),
                    "lag_1": float(index),
                    "rolling_mean_3": float(index),
                    "seasonal_lag_2": float(index),
                },
                target=float(index),
            )
            for index in (0, 1)
        ]
        test_rows = [
            FeatureRow(
                timestamp=2.0,
                router="r1",
                interface="eth1",
                link="r1-r2",
                features={
                    "current": 2.0,
                    "lag_1": 2.0,
                    "rolling_mean_3": 2.0,
                    "seasonal_lag_2": -1.0,
                },
                target=0.0,
            )
        ]

        for model in MODEL_NAMES:
            prediction = predict(model, train_rows=train_rows, test_rows=test_rows)

            self.assertEqual(len(prediction), 1)
            self.assertGreaterEqual(prediction[0], 0.0)
            self.assertLessEqual(prediction[0], 1.0)


if __name__ == "__main__":
    unittest.main()
