#!/usr/bin/env bash
source "$VIRTUAL_ENV/bin/activate"

ruff format --check custom_components/sax_battery/
ruff check custom_components/sax_battery/