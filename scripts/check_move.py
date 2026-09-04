import sys
import time

cur = float(sys.argv[1])
ref = float(sys.argv[2])
ref_time = float(sys.argv[3])
threshold = float(sys.argv[4])
window_seconds = float(sys.argv[5])

now = time.time()
pct = (cur - ref) / ref * 100 if ref else 0.0
alert = abs(pct) >= threshold
refresh = alert or (now - ref_time) >= window_seconds

print(f"{1 if alert else 0}\t{1 if refresh else 0}\t{pct:.2f}")
