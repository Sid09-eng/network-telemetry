# Forecast metrics

Source run: `task7-variable-traffic-20261115`. Metrics are utilization-ratio errors from completed collection.
Source manifest SHA-256: `334d4c7552a22420ddc7de203e9fb34fd56f146c5bf76b0624b01e6cc7f86af8`.
This is a short synthetic run, not an operator-network performance claim.

## Rolling-origin future-time evaluation

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.002772 | 0.005532 |
| seasonal_naive | 0.031210 | 0.064672 |
| ridge | 0.045179 | 0.085985 |
| hist_gradient_boosting | 0.023762 | 0.043166 |

## Leave-one-link-out transfer evaluation

### Held out: `h1-r1`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.000000 | 0.000001 |
| seasonal_naive | 0.000005 | 0.000009 |
| ridge | 0.000489 | 0.000489 |
| hist_gradient_boosting | 0.000034 | 0.000039 |

### Held out: `r1-r2`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.002382 | 0.005780 |
| seasonal_naive | 0.026048 | 0.059219 |
| ridge | 0.001613 | 0.003306 |
| hist_gradient_boosting | 0.001505 | 0.003010 |

### Held out: `r1-r3`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.000000 | 0.000000 |
| seasonal_naive | 0.000000 | 0.000000 |
| ridge | 0.000584 | 0.000584 |
| hist_gradient_boosting | 0.000112 | 0.000357 |

### Held out: `r2-r4`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.002478 | 0.005919 |
| seasonal_naive | 0.026203 | 0.059357 |
| ridge | 0.001718 | 0.003470 |
| hist_gradient_boosting | 0.001391 | 0.003091 |

### Held out: `r3-r4`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.000000 | 0.000000 |
| seasonal_naive | 0.000000 | 0.000000 |
| ridge | 0.000584 | 0.000584 |
| hist_gradient_boosting | 0.000042 | 0.000151 |

### Held out: `r4-h2`

| Model | MAE | RMSE |
| --- | ---: | ---: |
| persistence | 0.004914 | 0.008367 |
| seasonal_naive | 0.052365 | 0.083959 |
| ridge | 0.002952 | 0.004807 |
| hist_gradient_boosting | 0.001442 | 0.002685 |
