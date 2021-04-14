
import src.DMM34411A_class as dmm_class
import time
dmm = dmm_class.DMM_34411A()

dmm.conf_current_dc()

for i in range(10):
    print(dmm.measure_current_dc())

time.sleep(2)



dmm.close()