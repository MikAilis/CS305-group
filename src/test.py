import struct
from time import time

print(time())
ts = int(round(time() * 1000000))
print(time())
print(ts / 1000000)