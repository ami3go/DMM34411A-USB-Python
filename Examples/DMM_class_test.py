import DMM34411A_class
import time
dmm = DMM34411A_class.DMM_34411A()

dmm.conf_resistane_4wire()

for i in range(10):
    print(round(float(dmm.measure_resistnce_4wire()),6))

time.sleep(2)



dmm.close()