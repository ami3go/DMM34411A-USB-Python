"""Acquire 1,000 DC-voltage readings and save them in 34411A NVMEM."""

from src.DMM34411A_class import DMM_34411A

dmm = DMM_34411A()
try:
    dmm.conf_voltage_dc()
    dmm.configure_data_log(points=1_000, sample_interval_seconds=0.1)
    dmm.start_data_log()

    # Monitor RDG_STORE, wait for every reading, then copy them into the
    # 50,000-reading non-volatile store.
    saved_points = dmm.wait_for_data_log(timeout_seconds=120)
    readings = dmm.read_data_log()

    print(f"Saved {saved_points} readings in NVMEM")
    print(f"Read back {len(readings)} readings")
finally:
    dmm.close()
