"""Example against a deliberately selected physical DMM (never run by CI)."""

import os

from dmm34411a import DMM_34411A

# Explicitly choose the actual instrument; never silently use the legacy serial.
address = os.environ["DMM34411A_VISA_ADDRESS"]

with DMM_34411A(resource_name=address, timeout_s=10.0) as dmm:
    print("Connected:", dmm.idn)
    dmm.conf_current_dc()
    for _ in range(10):
        print(dmm.measure_current_dc())
