from time import time
MAX_PACKETS = 512

alpha = 0.125
beta = 0.25
MIN_RTO = 1 # seconds
MAX_RTO = 60 # seconds
K = 4 
G = 0.1 # Clock Granularity，usually <= 100 msec

class Sender2Reciever_Session:
    def __init__(self, peer_addr, chunkhash, rtt): # suppose that rtt is given fom cmd
        self.peer_addr = peer_addr
        self.chunkhash = chunkhash
        self.cwnd = 1 # initial cwnd size
        self.sendBase = 1 # ack head
        self.nextPktNum = 1
        self.timer_start = None
        self.isConstantRtt = (rtt != 0)
        self.RTT = rtt # retransmission timeout
        self.duplicate_acks = 0
        # 自适应rtt
        self.SRTT = None # smoothed round-trip time
        self.RTTVAR = None # round-trip time variation
        if not self.isConstantRtt:
            self.RTT = 1
    
    def open_timer(self):
        self.timer_start = time()
    
    def close_timer(self):
        self.timer_start = None
    
    def isTimeout(self):
        return time() - self.timer_start > self.RTT
    

    # 在计算RTT的时候要在estimatedRtt之前执行
    def DevRTT(self, sampleRtt): 
        if(self.RTTVAR is None):
            self.RTTVAR = sampleRtt / 2
        else:
            self.RTTVAR = (1 - beta) * self.RTTVAR + beta * abs(self.SRTT - sampleRtt)

    def estimatedRtt(self, sampleRtt):
        if(self.SRTT is None):
            self.SRTT = sampleRtt
        else:
            self.SRTT = (1 - alpha) * self.SRTT + alpha * sampleRtt
        
    def setRTT(self):
        res = self.SRTT + K * self.RTTVAR
        self.RTT = res
        # self.RTT = 1 if res < 1 else res

    def excuteRTT(self, sampleRtt):
        if not self.isConstantRtt:
            self.DevRTT(sampleRtt) # 必须在estimatedRtt前面执行
            self.estimatedRtt(sampleRtt)
            self.setRTT()

    def updateTimeoutRTT(self):
        if not self.isConstantRtt:
            self.RTT = min(MAX_RTO, self.RTT * 2)
            # self.RTTVAR = None
            # self.SRTT = None



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
