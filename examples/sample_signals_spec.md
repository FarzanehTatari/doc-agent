# Vehicle Speed Estimator (VSE) — Component Spec

## Purpose

The Vehicle Speed Estimator subsystem produces a filtered estimate of the
ego-vehicle's longitudinal speed in km/h, used by ADAS features (ACC, AEB) and
by the dashboard for the driver-visible speedometer.

## Inputs

- `vWheelFL_rps` — front-left wheel rotational speed (rad/s, float32)
- `vWheelFR_rps` — front-right wheel rotational speed (rad/s, float32)
- `tireRollingRadius_m` — calibration, dynamic effective rolling radius

## Outputs

- `vEgo_kmh` — estimated ego-vehicle speed (km/h, float32, sample rate 100 Hz)
- `vEgoStatus` — health flag (enum: OK, DEGRADED, INVALID)

## Algorithm

1. Average the two front-axle wheel speeds: `wAvg = (vWheelFL_rps + vWheelFR_rps) / 2`
2. Convert to linear speed: `vLin = wAvg * tireRollingRadius_m`
3. Apply a first-order discrete low-pass filter with time constant
   `K_VSE_FILT_TC` (default 0.05 s, range 0.01–1.0 s) to reduce sensor noise.
4. Convert m/s → km/h and clip to `[K_VSE_MIN_SPEED, K_VSE_MAX_SPEED]`.

## Calibrations

| Name              | Units | Default | Min | Max | Description                |
|-------------------|-------|---------|-----|-----|----------------------------|
| K_VSE_FILT_TC     | s     | 0.05    | 0.01| 1.0 | Low-pass filter time const |
| K_VSE_MIN_SPEED   | km/h  | 0.0     | 0.0 | 5.0 | Output floor               |
| K_VSE_MAX_SPEED   | km/h  | 300.0   | 100 | 400 | Output ceiling             |
| K_VSE_DIAG_GATE   | km/h  | 2.0     | 0.5 | 10  | Below this, mark DEGRADED  |

## Failure modes

- If either wheel-speed input is flagged invalid by the upstream Wheel Speed
  Reader, `vEgoStatus` becomes DEGRADED and the previous valid sample is held
  for up to 200 ms.
- If both inputs are invalid for more than 200 ms, `vEgoStatus` becomes INVALID
  and `vEgo_kmh` is set to 0.

## Notes

- All signals follow project naming conventions: camelCase with a lowercase
  unit suffix joined by an underscore.
- The estimator runs in the 10 ms task on the safety-domain ECU.
