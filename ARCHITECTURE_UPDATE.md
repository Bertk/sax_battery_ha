# SAX Battery Integration Architecture Update

## Changes Made

### 1. Documentation Updates

- Updated `.github/copilot-instructions.md` to clarify that:
  - Smart meter data is accessed through battery units via Modbus TCP/IP
  - Only the master battery polls smart meter data
  - Phase-specific data (L1/L2/L3) is polled at lower frequency (30-60 seconds)
  - Basic smart meter data is polled at standard interval (5-10 seconds)

### 2. Constants Refactoring (`const.py`)

- Added polling interval constants:
  - `BATTERY_POLL_INTERVAL = 10`  # Standard battery data polling
  - `SMARTMETER_POLL_INTERVAL = 10`  # Basic smart meter data polling  
  - `SMARTMETER_PHASE_POLL_INTERVAL = 60`  # L1/L2/L3 phase-specific data polling
- Separated smart meter items by polling frequency:
  - `MODBUS_SMARTMETER_BASIC_ITEMS`  # High frequency polling
  - `MODBUS_SMARTMETER_PHASE_ITEMS`  # Low frequency polling  
  - `MODBUS_SMARTMETER_ITEMS`  # Union of basic + phase items
- Created complete item union:
  - `MODBUS_ALL_ITEMS`  # Battery + smart meter items (used by master battery only)
- Added comprehensive sensor descriptions for all smart meter data points
- Maintained single-line formatting with `# fmt: off/on` protection

### 3. Models Enhancement (`models.py`)

- Added new methods to `SAXBatterySystem`:
  - `should_poll_smart_meter(battery_id)` - Check if battery should poll smart meter data
  - `get_polling_interval_for_battery(battery_id, data_type)` - Get appropriate polling intervals
  - `get_modbus_items_for_battery(battery_id)` - Get appropriate modbus items per battery
- Architecture clarifications:
  - Master battery: Polls all items (battery + smart meter data)
  - Slave batteries: Poll only their own battery data
  - Smart meter data sharing handled via RS485 communication between batteries

### 4. Key Architectural Changes

- **Smart meter polling responsibility**: Only master battery polls smart meter data
- **Data access pattern**: Smart meter data accessed through battery Modbus TCP/IP connections
- **Polling optimization**: Different frequencies for different data types:
  - Battery data: 10 seconds (all batteries)
  - Basic smart meter data: 10 seconds (master only)
  - Phase-specific data: 60 seconds (master only)
- **Data sharing**: Master battery shares smart meter data with slaves via RS485

## Implementation Notes

### Polling Strategy

```python
# Master battery polls:
realtime_items = MODBUS_BATTERY_REALTIME_ITEMS  # SOC, Power, Status
static_items = MODBUS_BATTERY_STATIC_ITEMS      # Capacity, Cycles, Temperature, Energy counters
smartmeter_items = MODBUS_SMARTMETER_ITEMS      # All smart meter data

realtime_interval = 10s     # Critical battery data
static_interval = 300s      # Accumulated/static data (5 minutes)
smartmeter_basic_interval = 10s    # Basic smart meter data
smartmeter_phase_interval = 60s    # L1/L2/L3 specific data

# Slave batteries poll:
items = MODBUS_BATTERY_REALTIME_ITEMS + MODBUS_BATTERY_STATIC_ITEMS  # Only battery data
realtime_interval = 10s     # Critical battery data
static_interval = 300s      # Accumulated/static data (5 minutes)
```

### Data Flow

1. Master battery polls smart meter data via its Modbus TCP/IP connection
2. Master battery shares grid measurements with slaves via RS485
3. All batteries coordinate power limits and system behavior
4. Home Assistant gets complete system view through master battery

### Benefits

- Reduced network traffic (only master polls smart meter)
- Optimized polling frequencies (less frequent for phase data and static values)
- Efficient resource usage (static data polled every 5 minutes vs 10 seconds)
- Centralized smart meter data management
- Maintains real-time coordination between batteries
- Scalable for multiple battery installations
- Reduced Modbus traffic for accumulated values (capacity, cycles, temperature, energy counters)

## Next Steps

- Update coordinator to implement different polling intervals
- Implement smart meter data sharing logic in RS485 communication
- Add configuration options for polling intervals
- Create separate entities for master vs slave battery data
- Add diagnostics for smart meter polling status
