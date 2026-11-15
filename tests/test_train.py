"""Training-to-detector integration tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from forecast.features import FeatureRow
from forecast.train import calibrate_and_publish_detector


class DetectorTrainingTests(unittest.TestCase):
    def test_calibrates_on_earlier_validation_folds_and_scores_the_final_fold(self) -> None:
        rows = [
            FeatureRow(
                timestamp=float(index),
                router="r1",
                interface="eth1",
                link="r1-r2",
                features={"current": index / 100, "seasonal_lag_1": index / 100},
                target=(index + 1) / 100,
            )
            for index in range(48)
        ]

        with (
            patch("forecast.train.configure_detector_threshold") as configure,
            patch("forecast.train.publish_detections") as publish,
        ):
            threshold, detections = calibrate_and_publish_detector(
                rows,
                detector_url="http://detector:8001",
                model="persistence",
                quantile=0.5,
            )

        self.assertAlmostEqual(threshold, 0.01)
        self.assertEqual([item.timestamp for item in detections], list(map(float, range(36, 48))))
        configure.assert_called_once_with(
            detector_url="http://detector:8001", threshold=threshold, dry_run=False
        )
        publish.assert_called_once_with(
            detector_url="http://detector:8001", detections=detections, dry_run=False
        )


if __name__ == "__main__":
    unittest.main()
