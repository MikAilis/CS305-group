from time import time
MAX_PACKETS = 512

class Sender2Reciever_Session:
    def __init__(self, peer_addr, chunkhash, rtt=None): # suppose that rtt is given fom cmd
        self.peer_addr = peer_addr
        self.chunkhash = chunkhash
        self.cwnd = 1 # initial cwnd size
        self.sendBase = 1 # ack head
        self.nextPktNum = 1
        self.timer_start = None
        self.RTT = rtt
        self.duplicate_acks = 0
    
    def open_timer(self):
        self.timer_start = time()
    
    def close_timer(self):
        self.timer_start = None
    
    def isTimeout(self):
        return time() - self.timer_start > self.RTT
    



class Reciever2Sender_Session:
    def __init__(self, peer_addr, chunkhash):
        self.peer_addr = peer_addr
        self.chunkhash = chunkhash
        self.pkts = [bytes() for _ in range(513)]
        self.waiting_pkt = 1
    
    def isFinished(self):
        return self.waiting_pkt == MAX_PACKETS+1
    
    def getChunkData(self):
        return bytes().join(self.pkts)