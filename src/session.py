from time import time

MAX_PACKETS = 512

alpha = 0.125
beta = 0.25
MIN_RTO = 1  # seconds, not used
MAX_RTO = 10  # seconds
K = 4
G = 0.1  # Clock Granularity，usually <= 100 msec; not used


class Sender2Reciever_Session:
    def __init__(self, timeout):  # suppose that timeout is given fom cmd
        # self.send_queue = [] # chunkhash str
        self.sending_chunkhash = None
        self.cwnd = 1  # initial cwnd size
        self.sendBase = 1  # ack head
        self.nextPktNum = 1
        self.timer_start = None
        self.duplicate_acks = 0
        # 自适应rto
        self.SRTT = None  # smoothed round-trip time
        self.RTTVAR = None  # round-trip time variation
        self.RTO = 1 if timeout == 0 else timeout  # retransmission timeout

    def open_timer(self):
        self.timer_start = time()

    def close_timer(self):
        self.timer_start = None

    def isTimeout(self):
        return time() - self.timer_start > self.RTO

    # 在计算RTO的时候要在estimatedRtt之前执行
    def DevRTT(self, sampleRtt):
        if (self.RTTVAR is None):
            self.RTTVAR = sampleRtt / 2
        else:
            self.RTTVAR = (1 - beta) * self.RTTVAR + beta * abs(self.SRTT - sampleRtt)

    def estimatedRtt(self, sampleRtt):
        if (self.SRTT is None):
            self.SRTT = sampleRtt
        else:
            self.SRTT = (1 - alpha) * self.SRTT + alpha * sampleRtt

    def setRTO(self):
        self.RTO = self.SRTT + K * self.RTTVAR

    def updateRTO(self, sampleRtt):
        self.DevRTT(sampleRtt)  # 必须在estimatedRtt前面执行
        self.estimatedRtt(sampleRtt)
        self.setRTO()

    def updateTimeoutRTO(self):
        self.RTO = min(MAX_RTO, self.RTO * 2)


class Reciever2Sender_Session:
    def __init__(self):
        self.start_time = None
        self.request_queue = []  # chunkhash str
        self.receiving_chunkhash = None
        self.pkts = [bytes() for _ in range(513)]
        self.waiting_pkt = 1

    def reset(self):
        self.receiving_chunkhash = None
        self.pkts = [bytes() for _ in range(513)]
        self.waiting_pkt = 1

    def isFinished(self):
        return self.waiting_pkt == MAX_PACKETS + 1

    def getChunkData(self):
        return bytes().join(self.pkts)

    def open_timer(self):  # 收到一个pkt就打开计时器
        self.start_time = time()

    def isCrash(self):
        return time() - self.start_time > MAX_RTO