#!/usr/bin/env python3
"""Verify expected SunSpec models and selected values over Modbus TCP.

sax-power supported models:

model 1: common (All SunSpec compliant devices must include this as the first model)
model 103: inverter_three_phase (Inverter Three Phase)
model 123: controls (specific device controls)
model 203: ac_meter_abcn (wye-connect three phase (abcn) meter)
model 802: battery (Battery Base Model)

documentation: https://github.com/sunspec/pysunspec2#full-example-of-a-device-interaction
"""

from __future__ import annotations

import sys
from typing import Any

from sunspec2.modbus import client

DEFAULT_IPADDR = "192.168.178.90"
DEFAULT_IPPORT = 502
DEFAULT_SLAVE_ID = 40


def prompt_with_default(prompt_text: str, default_value: str) -> str:
    """Prompt the user for input, providing a default value if no input is given."""
    user_input = input(f"{prompt_text} [{default_value}]: ").strip()
    return user_input or default_value


def trace_logger(message: str) -> None:
    """Log a Modbus trace message."""
    print(f"[MODBUS TRACE] {message}")  # noqa: T201


def verify_model(
    device: Any, attribute_name: str, model_id: int, fields: list[str]
) -> None:
    """Read the first instance of an expected model and print selected fields."""

    models = getattr(device, attribute_name, None)
    if not models:
        raise RuntimeError(
            f"Required SunSpec model {model_id} ({attribute_name}) is missing."
        )

    model = models[0]
    model.read()

    print(f"Model {model_id} ({attribute_name}) verified:")  # noqa: T201
    for field in fields:
        print(f"  {field}: {getattr(model, field, '<field unavailable>')}")  # noqa: T201


def main() -> int:
    """Main entry point for the script.

    Prompts the user for connection details, connects to the SunSpec device over Modbus TCP,
    verifies the presence of required models, and prints selected fields.

    Returns:
        int: Exit code (0 for success, 1 for verification failure, 2 for input errors).
    """
    ipaddr = prompt_with_default("Enter IP address", DEFAULT_IPADDR)

    try:
        ipport = int(prompt_with_default("Enter IP port", str(DEFAULT_IPPORT)))
        slave_id = int(prompt_with_default("Enter slave ID", str(DEFAULT_SLAVE_ID)))
    except ValueError:
        print("Port and slave ID must be integers.", file=sys.stderr)  # noqa: T201
        return 2

    if not 1 <= ipport <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)  # noqa: T201
        return 2

    if not 0 <= slave_id <= 247:
        print("Slave ID must be between 0 and 247.", file=sys.stderr)  # noqa: T201
        return 2

    device = client.SunSpecModbusClientDeviceTCP(
        slave_id=slave_id,
        ipaddr=ipaddr,
        ipport=ipport,
        timeout=5,
        trace_func=trace_logger,
    )

    try:
        device.connect()
        device.scan()

        print("Discovered models:")  # noqa: T201
        for model_id, model in device.models.items():
            print(f"  {model_id}: {model}")  # noqa: T201

        # Required firmware-update verification reads.
        verify_model(device, "common", 1, ["Mn", "Md", "Vr", "SN"])
        verify_model(device, "inverter_three_phase", 103, ["Pac"])
        verify_model(device, "controls", 123, ["Status"])
        verify_model(device, "ac_meter_abcn", 203, ["Reading"])
        verify_model(device, "battery", 802, ["SOC"])

        print("SunSpec firmware verification passed.")  # noqa: T201
        return 0  # noqa: TRY300
    except Exception as error:  # noqa: BLE001
        print(f"SunSpec firmware verification failed: {error}", file=sys.stderr)  # noqa: T201
        return 1
    finally:
        device.close()


if __name__ == "__main__":
    raise SystemExit(main())
