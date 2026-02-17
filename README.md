# SmartThings Energy Fix

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Fixes energy monitoring for Samsung TVs (including The Frame) in Home Assistant.

## Problem

Samsung TVs report `energy: 0` in the SmartThings `powerConsumption` capability. Actual consumption data goes to `deltaEnergy` — which the built-in SmartThings integration exposes as "Energy difference" but cannot be used in the Energy Dashboard.

## Solution

This integration reads `deltaEnergy` from the existing SmartThings integration and accumulates it into a running total. The resulting sensor is fully compatible with the HA Energy Dashboard (`state_class: total_increasing`).

- Does **not** override or modify the built-in SmartThings integration
- Attaches the sensor to the existing device in the device registry
- Only creates sensors for devices where `energy == 0` and `deltaEnergy > 0`
- Devices with working energy (fridge, washer, etc.) are unaffected

## Requirements

- Home Assistant with the built-in **SmartThings** integration configured and working

## Install (HACS)

1. Open HACS
2. Add this repository as a custom repository (category: Integration)
3. Install **SmartThings Energy Fix**
4. Restart Home Assistant
5. Settings → Devices & services → Add integration → **SmartThings Energy Fix** → Submit

## Result

A new sensor **Energy (accumulated)** appears on your Samsung TV device. Add it to the Energy Dashboard under electricity consumption.

| Sensor | Source | Energy Dashboard |
|---|---|---|
| Energy (built-in) | `energy` field — always 0 for TVs | No |
| Energy difference (built-in) | `deltaEnergy` field — per-window, not cumulative | No |
| **Energy (accumulated)** (this fix) | accumulated `deltaEnergy` — running total | **Yes** |

## Notes

- The accumulator resets on HA restart. This is expected — HA Long Term Statistics handles resets of `total_increasing` sensors correctly and continues summing from the new baseline.
- Polling interval: 60 seconds (reads from SmartThings integration data, no extra API calls).
