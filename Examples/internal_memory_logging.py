"""Safe 34411A memory logging over the selected VISA or Ethernet transport.

Operator must first check existing NVM and protect any saved instrument data.
There is NO automatic NVM deletion in this workflow.
"""

from dmm34411a import DMM_34411A

address = "USB0::0x0957::0x0A07::YOUR_SERIAL::0::INSTR"

with DMM_34411A(resource_name=address, timeout_s=10.0) as dmm:
    print(dmm.idn)
    print("Existing nonvolatile readings:", dmm.nonvolatile_point_count())
    if dmm.nonvolatile_point_count():
        raise RuntimeError("Back up existing NVM data; no automatic deletion")
    dmm.conf_voltage_dc()
    dmm.configure_data_log(points=1_000, sample_interval_seconds=0.1)
    dmm.start_data_log()
    saved = dmm.wait_for_data_log(timeout_seconds=120, poll_interval_seconds=0.2)
    samples = dmm.read_data_log()
    assert len(samples) == saved
    print(f"Saved {saved} instrument NVM readings")
