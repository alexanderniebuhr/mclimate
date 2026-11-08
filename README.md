# MClimate LoRaWAN for Home Assistant

Control MClimate LoRaWAN devices from Home Assistant through its LoRaWAN
integration. The integration talks to your existing LoRaWAN server connection,
so it needs no credentials of its own.

## Supported devices

| Device | Status |
| --- | --- |
| MClimate Vicki LoRaWAN (firmware 4.3 or later) | Supported |
| MClimate Vicki LoRaWAN (firmware before 4.3) | Measurements only |
| Other MClimate devices | Not supported |

## Prerequisites

- Home Assistant 2026.11.0 or later.
- A LoRaWAN connection in Home Assistant, using ChirpStack or The Things Stack.
- Each Vicki added on that server with the official device catalog entry. A
  hand-made device profile does not identify the model, so it is not matched.

## Installation

1. In Home Assistant, open the Marketplace and add this repository.
2. Install **MClimate LoRaWAN** and restart Home Assistant.
3. Home Assistant discovers your Vicki devices. Confirm the discovery, or add
   **MClimate LoRaWAN** under **Settings > Devices & services**.

Setup has no fields. One entry covers every Vicki on every LoRaWAN connection,
and devices added later appear automatically.

## Entities

| Entity | Notes |
| --- | --- |
| Climate | Current and target temperature, off and heat modes |
| Temperature, humidity | Measured by the device |
| Valve openness | Percent open, derived from the motor position |
| Open window, anti-freeze | Device status flags |
| Child lock | Locks the rotary ring |
| Operating mode | Automatic, automatic with external sensor, or manual valve control |
| Valve position | Sets the valve directly, only available in manual mode |
| Keep-alive period, temperature offset | Enabled by default |
| Minimum and maximum target on ring | Limits for turning the ring, commands can go beyond them |
| Open window detection, close time, temperature drop | Detection is off by default on the device |
| Battery voltage, battery low | Diagnostics |
| Temperature sensor broken, motor calibration failed, attached to backplate | Diagnostics |
| Battery, motor position, motor range, motor consumption | Diagnostics, disabled by default |
| Anti-freeze thresholds and target, offline target, automatic setback | Settings, disabled by default |
| Valve minimum and maximum, PI gains, integral limit, run period, hysteresis | Settings, disabled by default |
| Primary mode, display units, LED duration, keep child lock when offline, pause algorithm | Settings, disabled by default |
| Uplink type, join retry period, watchdog periods, restart | Settings, disabled by default |

Settings marked for firmware 4.4 or 4.6 by MClimate become unavailable on older
firmware. These are display units (4.4), and automatic setback, offline target,
LED duration, pause algorithm and the scale display (4.6).

## Options

Under **Configure** on the integration you can link a room temperature sensor to
each Vicki. The operating mode decides how it is used:

- **Automatic:** the device offset moves so its reading follows the sensor. It
  only changes for a difference of 0.5 °C or more, within the device limit of
  ±4.9 °C.
- **Automatic with external sensor:** the reading replaces the device sensor for
  the control algorithm. Open window detection keeps using the device sensor.

Each adjustment uses a downlink. Clear the field to unlink the sensor.

## How data updates

The Vicki is a LoRaWAN Class A device. It reports on its keep-alive period,
which is 10 minutes by default, and can only receive a command right after it
has sent an uplink.

Settings are not part of the keep-alive. After the firmware is known, Home
Assistant reads them in a few batches, one per uplink, so they fill in over the
first hour and again after each restart. Every change also asks the device to
report the value it applied.

A command therefore takes effect after the next keep-alive, and the device
reports the result in the one after that. Home Assistant shows the requested
value in the meantime. If the device still reports something else after two
uplinks, Home Assistant goes back to the reported value.

## Use cases and examples

Lower the temperature at night:

```yaml
automation:
  - alias: Bedroom night setback
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.bedroom_vicki
        data:
          temperature: 17
```

Get a reminder when the batteries run low:

```yaml
automation:
  - alias: Vicki battery low
    triggers:
      - trigger: state
        entity_id: binary_sensor.bedroom_vicki_battery_low
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: Replace the batteries in the bedroom Vicki.
```

## Known limitations

- The Vicki has no off command. **Off sets the target to 5 °C**, so the valve is
  not forced closed and frost protection stays active. A target of 5 °C always
  shows as off.
- Values stay unknown after a restart until the next keep-alive.
- Several commands sent within one keep-alive period are delivered one uplink
  at a time, so the displayed value can briefly jump back.
- Manual mode ignores the target temperature, so it is refused there. On
  firmware 5.0 and later the device returns to automatic after 12 hours without
  a motor command.
- A valve change must move the motor by at least 17 steps, because MClimate warns
  that smaller moves make the device misbehave.
- Automatic setback, offline target and the watchdog depend on when the device
  considers itself offline. By default it resets after 24 hours without any
  downlink when using unconfirmed uplinks.
- Scale display levels are not configurable.

These are deliberately not exposed: force-close and recalibration, which MClimate
says must be avoided, force-attach, which must not be used on firmware 4.5 or 4.6,
changing the AppEUI and AppKey, HT Sensor pairing, and heating schedules.

## Troubleshooting

- **No supported devices found**: check that the device on your LoRaWAN server
  uses the official MClimate Vicki catalog entry.
- **Set up a LoRaWAN connection first**: set up the ChirpStack or The Things
  Stack integration before this one.
- **A change does not show up**: wait for two keep-alive periods. If the value
  reverts, check for failed downlinks on your LoRaWAN server.
- **Entities are unavailable**: the connection to your LoRaWAN server was lost.
  They return when it is restored.

## Removal

1. Under **Settings > Devices & services**, open **MClimate LoRaWAN** and delete
   the entry.
2. Uninstall the integration from the Marketplace.

Your devices stay on your LoRaWAN server and keep their last target temperature.
