import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import select
import util.simsocket as simsocket
import struct
import socket
import util.bt_utils as bt_utils
import hashlib
import argparse
import pickle
from time import time
from session import Reciever2Sender_Session, Sender2Reciever_Session

BUF_SIZE = 1400
MAX_PAYLOAD = 1024
CHUNK_DATA_SIZE = 512*1024 # 单位也是byte，512KB
HEADER_LEN = struct.calcsize("!HBBHHIIQ") # header加上了时间戳

config = None
outputFile = None

# addr标识
r_sessions = {} # recevier session 
s_sessions = {} # send session 
peer_chunkhash = {} # addr-hash: peer对应的chunkhash
chunkhash_peer = {} # hash-addr：chunkhash对应的peer
chunkhash_chunkdata = {} # hash-data：下载完填入该字典中

# 正在发送的chunk
sending_chunkhash = set()

totalWant = 0

# download in cmd
def process_download(sock,chunkfile, outputfile):
    global totalWant
    global outputFile
    outputFile = outputfile
    want_hash = bytes()
    with open(chunkfile, 'r') as cf:
        lines = cf.readlines()
        for line in lines:
            index, datahash_str = line.strip().split(" ")
            totalWant += 1
            # hex_str to bytes
            datahash = bytes.fromhex(datahash_str)
            print(f'I ({config.identity}) says: who has {datahash_str}')
            want_hash += datahash
    print()
    # whohas pkt
    whohas_pkt = struct.pack("!HBBHHIIQ", 52305,93, 0, HEADER_LEN, 
                    HEADER_LEN+len(want_hash), 0, 0, 0) + want_hash
    # flooding
    peer_list = config.peers
    for p in peer_list:
        if int(p[0]) != config.identity:
            sock.sendto(whohas_pkt, (p[1], int(p[2])))

def process_inbound_udp(sock):
    global r_sessions
    global s_sessions
    global peer_chunkhash
    global chunkhash_peer
    global chunkhash_chunkdata
    global sending_chunkhash

    # Receive pkt
    pkt, from_addr = sock.recvfrom(BUF_SIZE)
    Magic, Team, Type,hlen, plen, Seq, Ack, sendingTS= struct.unpack("!HBBHHIIQ", pkt[:HEADER_LEN])
    data = pkt[HEADER_LEN:]
    if Type == 0: # WHOHAS pkt
        chunks_num = len(data) // 20
        has_chunkHash = bytes()
        for i in range(chunks_num):
            require_chunkHash = data[i*20:i*20+20]
            # bytes to hex_str
            require_chunkHash_str = bytes.hex(require_chunkHash)
            print(f"whohas: {require_chunkHash_str}, has: {list(config.haschunks.keys())}")
            if require_chunkHash_str in config.haschunks:
                has_chunkHash += require_chunkHash
        # send ihave pkt
        ihave_header = struct.pack("!HBBHHIIQ", 52305, 93, 1, HEADER_LEN, 
                    HEADER_LEN+len(has_chunkHash), 0, 0, 0)
        ihave_pkt = ihave_header+has_chunkHash
        sock.sendto(ihave_pkt, from_addr)

    elif Type == 1: # IHAVE pkt
        print(f'{from_addr} coming!')
        chunks_num = len(data) // 20
        # build connection
        receiver_session = Reciever2Sender_Session()

        for i in range(chunks_num):
            chunkHash = data[i*20:i*20+20]
            chunkhash_str = bytes.hex(chunkHash)
            print(f'{from_addr} have {chunkhash_str}')
            # add to peer_chunkhash
            if from_addr not in peer_chunkhash:
                peer_chunkhash[from_addr] = []
            peer_chunkhash[from_addr].append(chunkhash_str)
            # add to chunkhash_peer
            if chunkhash_str not in chunkhash_peer:
                chunkhash_peer[chunkhash_str] = []
            chunkhash_peer[chunkhash_str].append(from_addr)

            # add to queue
            receiver_session.request_queue.append(chunkhash_str)
        
        while True:
            if len(receiver_session.request_queue) == 0:
                break
            hash = receiver_session.request_queue.pop(0)
            if hash not in chunkhash_chunkdata and hash not in sending_chunkhash:
                r_sessions[from_addr] = receiver_session
                sending_chunkhash.add(hash)
                # send get pkt
                get_header = struct.pack("!HBBHHIIQ", 52305, 93, 2, HEADER_LEN, 
                            HEADER_LEN+len(hash), 0, 0, 0)
                get_pkt = get_header+bytes.fromhex(hash)
                sock.sendto(get_pkt, from_addr)
                receiver_session.receiving_chunkhash = hash ###
                print(f'I send get pkt to {from_addr} with payload: {hash}')
                break
        print()
        

    elif Type == 2: # GET pkt
        # create sender session
        sender_session = Sender2Reciever_Session(config.timeout)
        s_sessions[from_addr] = sender_session
        chunkhash_str = bytes.hex(data)
        chunkdata = config.haschunks[chunkhash_str]

        # 第一次get的cwnd肯定是1，只发送一个包
        send_data = chunkdata[:MAX_PAYLOAD]
        sender_session.open_timer() # 开启计时器
        # send one DATA pkt
        data_header = struct.pack("!HBBHHIIQ", 52305,93, 3, HEADER_LEN, 
                    HEADER_LEN+len(send_data), 1, 0,int(round(time() * 1000000)))
        sock.sendto(data_header+send_data, from_addr)
        sender_session.sending_chunkhash = chunkhash_str ###

        print(f'chunkhash: {chunkhash_str},seq: {1}.I send to {from_addr} data pkt with payload: {bytes.hex(send_data)}')
        print()
        # 更新发送窗口
        sender_session.sendBase = 1
        sender_session.nextPktNum = sender_session.nextPktNum + 1

    elif Type == 3: # DATA pkt
        receiver_session = r_sessions[from_addr]
        chunkhash = receiver_session.receiving_chunkhash
        print(f'length of data: {len(data)}')
        print(f'chunkhash: {chunkhash}, seq: {Seq}. I recevie from {from_addr} data pkt with payload: {bytes.hex(data)}')
        if len(receiver_session.pkts[Seq]) == 0: # cache
                receiver_session.pkts[Seq] = data
        if Seq == receiver_session.waiting_pkt:
            while True:
                if receiver_session.isFinished():
                    break
                if len(receiver_session.pkts[receiver_session.waiting_pkt]) != 0:
                    receiver_session.waiting_pkt += 1
                else:
                    break
            ack_pkt = struct.pack("!HBBHHIIQ", 52305,93, 4, HEADER_LEN, HEADER_LEN, 
                        0, receiver_session.waiting_pkt, sendingTS)
            print(f'chunkhash: {chunkhash}, ack: {receiver_session.waiting_pkt}.I send ack pkt to {from_addr}')
            sock.sendto(ack_pkt, from_addr)
        elif Seq > receiver_session.waiting_pkt: # send duplicate ack
            ack_pkt = struct.pack("!HBBHHIIQ", 52305,93, 4, HEADER_LEN, HEADER_LEN,
                            0, receiver_session.waiting_pkt, sendingTS)
            print(f'chunkhash: {chunkhash}, ack: {receiver_session.waiting_pkt}.I send ack pkt to {from_addr}----duplicate ack')
            sock.sendto(ack_pkt, from_addr)
        print()

        # see if the session is finished
        if receiver_session.isFinished():
            # global chunkhash_chunkdata
            chunkdata = receiver_session.getChunkData()
            chunkhash_chunkdata[chunkhash] = chunkdata
            sending_chunkhash.remove(chunkhash)
            # 更新receiver session
            receiver_session.reset()
            # 处理队列
            while True:
                if len(receiver_session.request_queue) == 0:
                    del r_sessions[from_addr]
                    break
                hash = receiver_session.request_queue.pop(0)
                if (hash not in chunkhash_chunkdata) and (hash not in sending_chunkhash):
                    sending_chunkhash.add(hash)
                    # send get pkt
                    get_header = struct.pack("!HBBHHIIQ", 52305, 93, 2, HEADER_LEN, 
                                HEADER_LEN+len(hash), 0, 0, 0)
                    get_pkt = get_header+bytes.fromhex(hash)
                    sock.sendto(get_pkt, from_addr)
                    receiver_session.receiving_chunkhash = hash ###
                    print(f'I send get pkt to {from_addr} with payload: {hash}')
                    break
            
        # see if all chunks are downloaded
        if len(chunkhash_chunkdata) == totalWant:
            # dump to output file
            with open(outputFile, "wb") as wf:
                pickle.dump(chunkhash_chunkdata, wf)
            # print GET message
            print(f"GET {outputFile}")

            # The following things are just for illustration, you do not need to print out in your design.
            sha1 = hashlib.sha1()
            sha1.update(chunkdata)
            received_chunkhash_str = sha1.hexdigest()
            print(f"Expected chunkhash: {chunkhash}")
            print(f"Received chunkhash: {received_chunkhash_str}")
            success = chunkhash == received_chunkhash_str
            print(f"Successful received: {success}")
            if success:
                print("Congrats! You have completed the example!")
            else:
                print("Example fails. Please check the example files carefully.")

    elif Type == 4: # ACK pkt
        # get session
        sender_session = s_sessions[from_addr]
        chunkhash = sender_session.sending_chunkhash
        print(f'chunkhash: {chunkhash}, Ack: {Ack}. I recevie ack pkt from {from_addr}')

        sampleRtt = time() - (sendingTS / 1000000)
        print('sampleRtt:', sampleRtt)
        # update RTO if timeout is not set in cmd
        if config.timeout == 0:
            sender_session.updateRTO(sampleRtt)
        print('RTO:', sender_session.RTO)

        chunkhash = sender_session.sending_chunkhash

        if (Ack-1)*MAX_PAYLOAD >= CHUNK_DATA_SIZE: # finished
            print(f"finished sending {chunkhash}")
            sender_session.sending_chunkhash = None
            del s_sessions[from_addr]
        else: # not finished
            if(Ack > sender_session.sendBase): # send new data
                sender_session.sendBase = Ack
                if(sender_session.sendBase != sender_session.nextPktNum):
                    sender_session.open_timer()
                else:
                    sender_session.close_timer()
                while sender_session.nextPktNum <= sender_session.sendBase+sender_session.cwnd-1:
                    send_data = config.haschunks[chunkhash][(sender_session.nextPktNum-1)*MAX_PAYLOAD: sender_session.nextPktNum*MAX_PAYLOAD]
                    new_pkt = struct.pack("!HBBHHIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data),
                            sender_session.nextPktNum, 0, int(round(time() * 1000000))) + send_data
                    print(f'chunkhash: {chunkhash}, seq = {sender_session.nextPktNum}. I send data pkt to {from_addr} with payload: {bytes.hex(send_data)}')
                    if sender_session.timer_start is None:
                        sender_session.open_timer()
                    sock.sendto(new_pkt, from_addr)
                    sender_session.nextPktNum += 1
            else: # duplicate ACKs
                sender_session.duplicate_acks += 1
                if(sender_session.duplicate_acks == 3):
                    # fast retransmit
                    send_data = config.haschunks[chunkhash][(sender_session.sendBase-1)*MAX_PAYLOAD: sender_session.sendBase*MAX_PAYLOAD]
                    retransmit_pkt = struct.pack("!HBBHHIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data),
                            sender_session.sendBase, 0, int(round(time() * 1000000)))
                    print(f'chunkhash: {chunkhash}, seq = {sender_session.sendBase}. I send data pkt to {from_addr} with payload: {bytes.hex(send_data)}')
                    sock.sendto(retransmit_pkt, from_addr)
        print()
    

def process_user_input(sock):
    command, chunkf, outf = input().split(' ')
    if command == 'DOWNLOAD':
        process_download(sock ,chunkf, outf)
    else:
        pass

def peer_run(config):
    addr = (config.ip, config.port)
    sock = simsocket.SimSocket(config.identity, addr, verbose=config.verbose)

    try:
        while True:
            ready = select.select([sock, sys.stdin],[],[], 0.1)
            read_ready = ready[0]
            if len(read_ready) > 0:
                if sock in read_ready:
                    process_inbound_udp(sock)
                if sys.stdin in read_ready:
                    process_user_input(sock)
            else:
                # No pkt nor input arrives during this period 
                pass
            for from_addr, sender_session in s_sessions.items():
                if sender_session.isTimeout(): # timeout retransmit
                    sender_session.updateTimeoutRTO()
                    print('retransmit RTT:', sender_session.RTO)
                    chunkhash = sender_session.sending_chunkhash
                    send_data = config.haschunks[chunkhash][(sender_session.sendBase-1)*MAX_PAYLOAD: sender_session.sendBase*MAX_PAYLOAD]
                    retransmit_pkt = struct.pack("!HBBHHIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data), 
                                    sender_session.sendBase, 0, int(round(time() * 1000000))) + send_data
                    print(f'chunkhash: {chunkhash}, seq: {sender_session.sendBase}.I retransmit pkt to {from_addr}')
                    sender_session.open_timer()
                    sock.sendto(retransmit_pkt, from_addr)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == '__main__':
    """
    -p: Peer list file, it will be in the form "*.map" like nodes.map.
    -c: Chunkfile, a dictionary dumped by pickle. It will be loaded automatically in bt_utils. The loaded dictionary has the form: {chunkhash: chunkdata}
    -m: The max number of peer that you can send chunk to concurrently. If more peers ask you for chunks, you should reply "DENIED"
    -i: ID, it is the index in nodes.map
    -v: verbose level for printing logs to stdout, 0 for no verbose, 1 for WARNING level, 2 for INFO, 3 for DEBUG.
    -t: pre-defined timeout. If it is not set, you should estimate timeout via RTT. If it is set, you should not change this time out.
        The timeout will be set when running test scripts. PLEASE do not change timeout if it set.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', type=str, help='<peerfile>     The list of all peers', default='nodes.map')
    parser.add_argument('-c', type=str, help='<chunkfile>    Pickle dumped dictionary {chunkhash: chunkdata}')
    parser.add_argument('-m', type=int, help='<maxconn>      Max # of concurrent sending')
    parser.add_argument('-i', type=int, help='<identity>     Which peer # am I?')
    parser.add_argument('-v', type=int, help='verbose level', default=0)
    parser.add_argument('-t', type=int, help="pre-defined timeout", default=0)
    args = parser.parse_args()

    config = bt_utils.BtConfig(args)
    peer_run(config)
