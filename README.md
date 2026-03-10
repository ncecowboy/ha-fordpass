# ha-fordpass

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

A Home Assistant custom integration for Ford vehicles using the FordPass app credentials. Based on [itchannel/fordpass-ha](https://github.com/itchannel/fordpass-ha) 1.80-Beta5, updated for the November 2025 Ford API changes and current Home Assistant compatibility.

## Important: Authentication Change

Ford has changed their authentication system. You can no longer authenticate directly with your username and password. Instead, you must obtain an authorization token via a browser redirect:

1. During setup, a login URL will be generated and shown to you
2. Open that URL in your browser and sign in with your Ford account
3. After signing in, your browser will be redirected to a URL starting with `fordapp://userauthorized/?code=...`
4. Copy the **entire** redirect URL and paste it into the Token field in Home Assistant

Tokens are stored in HA's storage system and will persist across restarts.

## Installation

Use [HACS](https://hacs.xyz/) to add this repository as a custom repo. Upon installation navigate to your integrations, and follow the configuration options.

## API Changes (November 2025)

This integration uses the updated Ford API endpoints:
- Vehicle status: `https://api.vehicle.ford.com/api`
- Guard/token API: `https://api.foundational.ford.com/api`
- Telemetry: Autonomic AI API

## Services

### refresh_status
Poll the car for latest status. Takes up to 5 minutes to update after calling.
Optionally specify a `vin` parameter to refresh only a specific vehicle.

### clear_tokens
Clear the cached authentication tokens (use if experiencing auth issues).

### poll_api
Manually trigger an API data refresh.

### reload
Reload the FordPass integration.

## Supported Regions

- Netherlands
- UK & Europe
- Australia
- USA
- Canada

## Supported Entities

- **Sensors**: Odometer, Fuel/Battery %, 12V Battery, Oil Life, Tire Pressure, Alarm, Ignition Status, Door Status, Window Position, Last Refresh, EV Battery Range, EV Charging Status, Speed, Engine Indicators, Coolant Temp, Outside Temp, Engine Oil Temp, Deep Sleep Mode, Remote Start Status, Diesel System Status, Exhaust Fluid Level
- **Lock**: Door lock/unlock
- **Switch**: Remote start (ignition)
- **Device Tracker**: GPS location

## Credits

- [itchannel](https://github.com/itchannel) - Original FordPass HA integration
- [SquidBytes](https://github.com/SquidBytes) - EV updates and documentation
- [marq24](https://github.com/marq24) - fordpass-ha fork with websockets
