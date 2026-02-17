"""Accumulating energy sensor for Samsung devices using deltaEnergy."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from pysmartthings import Attribute, Capability

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)


def _get_power_consumption(device) -> dict[str, Any] | None:
    """Extract powerConsumption dict from a SmartThings FullDevice."""
    try:
        status = device.status.get("main", {})
        cap = status.get(Capability.POWER_CONSUMPTION_REPORT, {})
        attr = cap.get(Attribute.POWER_CONSUMPTION)
        if attr is not None and attr.value is not None:
            return attr.value
    except Exception:
        pass
    return None


def _needs_delta_fix(report: dict[str, Any]) -> bool:
    """True if device reports energy=0 and has a deltaEnergy field.

    Does not require deltaEnergy > 0 at this moment — the device may be
    off or between reporting windows. The sensor will accumulate once
    deltaEnergy starts arriving.
    """
    energy = report.get("energy", 0)
    return (
        (not isinstance(energy, (int, float)) or energy == 0)
        and "deltaEnergy" in report
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up energy sensors for SmartThings devices needing deltaEnergy fix."""

    # Find all SmartThings config entries.
    st_entries = hass.config_entries.async_entries("smartthings")
    if not st_entries:
        _LOGGER.warning("No SmartThings integration found")
        return

    entities: list[SensorEntity] = []

    for st_entry in st_entries:
        runtime_data = getattr(st_entry, "runtime_data", None)
        if runtime_data is None:
            _LOGGER.debug("SmartThings entry %s has no runtime_data yet", st_entry.entry_id)
            continue

        devices = getattr(runtime_data, "devices", None)
        if not isinstance(devices, dict):
            continue

        for device_id, full_device in devices.items():
            report = _get_power_consumption(full_device)
            if report is None:
                continue

            # Only create sensor for devices where energy is broken (always 0).
            if not _needs_delta_fix(report):
                _LOGGER.debug(
                    "Device %s has working energy=%s, skipping",
                    device_id,
                    report.get("energy"),
                )
                continue

            _LOGGER.info(
                "Creating accumulating energy sensor for %s (%s)",
                full_device.device.label,
                device_id,
            )

            coordinator = SmartThingsEnergyCoordinator(
                hass, st_entry, device_id, full_device
            )
            await coordinator.async_config_entry_first_refresh()
            entities.append(AccumulatingEnergySensor(coordinator, full_device))

    async_add_entities(entities)


class SmartThingsEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that reads powerConsumption from SmartThings runtime_data."""

    def __init__(self, hass, st_entry, device_id, full_device) -> None:
        """Init the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_id}",
            update_interval=SCAN_INTERVAL,
        )
        self._st_entry = st_entry
        self._device_id = device_id
        self._device_label = full_device.device.label or device_id

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch power consumption from SmartThings runtime data."""
        runtime_data = getattr(self._st_entry, "runtime_data", None)
        if runtime_data is None:
            return {}

        devices = getattr(runtime_data, "devices", None)
        if not isinstance(devices, dict):
            return {}

        full_device = devices.get(self._device_id)
        if full_device is None:
            return {}

        report = _get_power_consumption(full_device)
        return report if isinstance(report, dict) else {}


class AccumulatingEnergySensor(CoordinatorEntity, SensorEntity):
    """Energy sensor that accumulates deltaEnergy into a running total.

    Compatible with HA Energy Dashboard (state_class: total_increasing).
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: SmartThingsEnergyCoordinator, full_device) -> None:
        """Init the sensor."""
        super().__init__(coordinator)
        device = full_device.device
        self._attr_unique_id = f"{device.device_id}_deltaenergy_accumulated"
        self._attr_name = "Energy (accumulated)"
        self._attr_device_info = {
            "identifiers": {("smartthings", device.device_id)},
        }
        self._accumulated_wh: float = 0.0
        self._last_report_end: str | None = None

    @property
    def native_value(self) -> float | None:
        """Return accumulated energy in kWh."""
        report = self.coordinator.data
        if not isinstance(report, dict) or not report:
            if self._accumulated_wh > 0:
                return round(self._accumulated_wh / 1000, 3)
            return None

        delta_energy = report.get("deltaEnergy", 0)
        if not isinstance(delta_energy, (int, float)):
            delta_energy = 0

        # Use the report "end" timestamp to avoid double-counting.
        end = report.get("end")
        if end and end != self._last_report_end and delta_energy > 0:
            self._accumulated_wh += delta_energy
            self._last_report_end = end

        return round(self._accumulated_wh / 1000, 3) if self._accumulated_wh > 0 else 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes for debugging."""
        report = self.coordinator.data
        if not isinstance(report, dict) or not report:
            return None
        return {
            "source": "deltaEnergy",
            "last_delta_wh": report.get("deltaEnergy"),
            "report_start": report.get("start"),
            "report_end": report.get("end"),
            "accumulated_wh": round(self._accumulated_wh, 3),
        }
