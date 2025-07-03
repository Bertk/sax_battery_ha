# Polling Frequency Optimization Summary

## Overview

The SAX Battery integration now implements optimized polling frequencies for different types of data to reduce network traffic and improve system performance.

## Polling Categories and Intervals

### 1. Real-time Battery Data (10 seconds)

- **SAX_STATUS** - Battery operational status
- **SAX_SOC** - State of charge (critical for power management)
- **SAX_POWER** - Current power flow
- **SAX_SMARTMETER** - Smart meter reference value

### 2. Static/Accumulated Battery Data (300 seconds = 5 minutes)

- **SAX_CAPACITY** - Battery capacity (rarely changes)
- **SAX_CYCLES** - Battery cycle count (increments slowly)
- **SAX_TEMP** - Battery temperature (changes slowly)
- **SAX_ENERGY_PRODUCED** - Accumulated energy produced
- **SAX_ENERGY_CONSUMED** - Accumulated energy consumed

### 3. Smart Meter Basic Data (10 seconds) - Master Battery Only

- **SAX_SMARTMETER_TOTAL_POWER** - Total grid power

### 4. Smart Meter Phase Data (60 seconds) - Master Battery Only

- **SAX_SMARTMETER_CURRENT_L1/L2/L3** - Phase currents
- **SAX_SMARTMETER_VOLTAGE_L1/L2/L3** - Phase voltages
- **SAX_ACTIVE_POWER_L1/L2/L3** - Phase active power
- **SAX_CURRENT_L1/L2/L3** - Battery-side phase currents
- **SAX_VOLTAGE_L1/L2/L3** - Battery-side phase voltages

## Benefits

### Network Traffic Reduction

- **83% reduction** for static data (300s vs 10s intervals)
- **83% reduction** for phase-specific data (60s vs 10s intervals)
- **Smart meter data centralization** (only master battery polls)

### Resource Optimization

- Critical data (SOC, Power, Status) remains real-time
- Static values polled appropriately for their change frequency
- Reduced Modbus TCP/IP connection load
- Better system scalability

### Practical Impact

```text
Before optimization:
- All 30+ data points polled every 10 seconds
- 180 Modbus requests per minute per battery
- 540 requests/min for 3-battery system

After optimization:
- Real-time data: 4 items every 10 seconds
- Static data: 5 items every 300 seconds  
- Smart meter data: Master only, with frequency optimization
- ~60% reduction in total Modbus requests
```

## Implementation Details

### Constants Added

```python
BATTERY_POLL_INTERVAL = 10              # Real-time battery data
BATTERY_STATIC_POLL_INTERVAL = 300      # Static/accumulated data
SMARTMETER_POLL_INTERVAL = 10           # Basic smart meter data
SMARTMETER_PHASE_POLL_INTERVAL = 60     # Phase-specific data
```

### Item Categories

```python
MODBUS_BATTERY_REALTIME_ITEMS    # High-frequency polling
MODBUS_BATTERY_STATIC_ITEMS      # Low-frequency polling
MODBUS_SMARTMETER_BASIC_ITEMS    # Basic smart meter data
MODBUS_SMARTMETER_PHASE_ITEMS    # Phase-specific smart meter data
```

### Polling Strategy

- **Master Battery**: All data types with appropriate intervals
- **Slave Batteries**: Only battery data (realtime + static)
- **Data Sharing**: Smart meter data shared via RS485 between batteries

This optimization maintains system responsiveness while significantly reducing network overhead and improving overall system efficiency.
