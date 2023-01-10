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

"""
This is CS305 project skeleton code.
Please refer to the example files - example/dumpreceiver.py and example/dumpsender.py - to learn how to play with this skeleton.
"""

BUF_SIZE = 1400
MAX_PAYLOAD = 1024
CHUNK_DATA_SIZE = 512*1024 # 单位也是byte，512KB
HEADER_LEN = struct.calcsize("!HBBHHIIIQ") # 在最后面添加了chunk对应的id值

config = None
outputFile = None
chunkid_chunkhash = {} # id-hash
chunkhash_chunkid = {} # hash-id
r_sessions = {} # recevier session
s_sessions = {} # send session
peer_chunkid = {} # port-id
chunkid_peer = {} # id-port
chunkhash_chunkdata = {} # hash-data
cnt = 0

def preperation():
    global chunkid_chunkhash
    global chunkhash_chunkid
    print('print master.chunkhash now !!!')
    with open('master.chunkhash', mode='r') as f:
        lines = f.readlines()
        for line in lines:
            id, chunkhash = line.strip().split(" ")
            id = int(id)
            chunkid_chunkhash[id] = chunkhash  # int-string
            chunkhash_chunkid[chunkhash] = id # string-int
            print(f'{id} {chunkhash}')
        print()

# download指令
def process_download(sock,chunkfile, outputfile):
    global outputFile

    outputFile = outputfile
    #read chunkhash to be downloaded
    download_hash = bytes()
    with open(chunkfile, 'r') as cf:
        lines = cf.readlines()
        for line in lines:
            index, datahash_str = line.strip().split(" ")
            # hex_str to bytes
            datahash = bytes.fromhex(datahash_str)
            print(f'{config.identity} says: who has {datahash_str}')
            download_hash = download_hash + datahash
    print()
    # whohas pkt
    whohas_header = struct.pack("!HBBHHIIIQ", 52305,93, 0, HEADER_LEN, 
                    HEADER_LEN+len(download_hash), 0, 0, 0, 0)
    whohas_pkt = whohas_header + download_hash

    # flooding
    peer_list = config.peers
    for p in peer_list:
        if int(p[0]) != config.identity:
            sock.sendto(whohas_pkt, (p[1], int(p[2])))


# 处理接受的pkt
def process_inbound_udp(sock):
    global s_sessions
    global peer_chunkid
    global chunkid_peer
    global r_sessions
    global chunkhash_chunkdata

    # Receive pkt
    pkt, from_addr = sock.recvfrom(BUF_SIZE)
    Magic, Team, Type,hlen, plen, Seq, Ack, chunkid, timestamp= struct.unpack("!HBBHHIIIQ", pkt[:HEADER_LEN])
    data = pkt[HEADER_LEN:]

    if(Type == 0): # WHOHAS
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
        ihave_header = struct.pack("!HBBHHIIIQ", 52305, 93, 1, HEADER_LEN, 
                    HEADER_LEN+len(has_chunkHash), 0, 0, 0, 0)
        ihave_pkt = ihave_header+has_chunkHash
        sock.sendto(ihave_pkt, from_addr)

    elif(Type == 1): # IHAVE
        global cnt

        chunks_num = len(data) // 20
        print(f'{from_addr} coming!')
        for i in range(chunks_num):
            peer_chunkHash = data[i*20:i*20+20]
            peer_chunkhash_str = bytes.hex(peer_chunkHash)
            print(f'{from_addr} have {peer_chunkhash_str}')
            id = chunkhash_chunkid[peer_chunkhash_str]
            # add to peer_chunkid
            if(from_addr not in peer_chunkid):
                peer_chunkid[from_addr] = []
            peer_chunkid[from_addr].append(id)
            # add to chunkid_peer
            if(id not in chunkid_peer):
                chunkid_peer[id] = []
            chunkid_peer[id].append(from_addr)
        print()
        cnt += 1

        # 收到了所有人的ihave
        if cnt == len(config.peers)-1:
            print('I should send GET now!!!')
            for id, peer_addr in chunkid_peer.items():
                chosen_peer = peer_addr[0] # 选第一个人
                chunkhash_str = chunkid_chunkhash[id]
                chunkhash = bytes.fromhex(chunkhash_str)
                # send back GET pkt
                get_header = struct.pack("!HBBHHIIIQ", 52305, 93, 2 , HEADER_LEN, 
                            HEADER_LEN+len(chunkhash), 0, 0, id, 0)
                get_pkt = get_header+chunkhash
                sock.sendto(get_pkt, chosen_peer)
                print(f'chunkid: {id}.I send get pkt to {from_addr} with payload: {chunkhash_str}')
                # create reciever2sender session
                r_sessions[id] = Reciever2Sender_Session(chosen_peer, chunkhash)
            print()

    elif(Type == 2): # GET
        # create sender2recevier session
        data_str = bytes.hex(data)
        id = chunkhash_chunkid[data_str]
        new_session = Sender2Reciever_Session(from_addr, data, config.timeout)
        s_sessions[id] = new_session

        chunkdata = config.haschunks[data_str]
        # 第一次get的cwnd肯定是1，只发送一个包
        new_session.open_timer() # 开启计时器
        send_data = chunkdata[:MAX_PAYLOAD]
        # send one DATA pkt
        data_header = struct.pack("!HBBHHIIIQ", 52305,93, 3, HEADER_LEN, 
                    HEADER_LEN+len(send_data), 1, 0, chunkid,int(round(time() * 1000000)))
        sock.sendto(data_header+send_data, from_addr)
        
        print(f'chunkid: {chunkid}, seq: {1}.I send to {from_addr} data pkt with payload: {bytes.hex(send_data)}')
        print()
        # 更新发送窗口
        new_session.sendBase = 1
        new_session.nextPktNum = new_session.nextPktNum + 1

    elif(Type == 3): # DATA
        print(f'length of data: {len(data)}')
        print(f'chunkid: {chunkid}, seq: {Seq}. I recevie from {from_addr} data pkt with payload: {bytes.hex(data)}')
        if chunkid not in r_sessions: # 来晚的pkt
            return
        
        now_session = r_sessions[chunkid]
        if len(now_session.pkts[Seq]) == 0: # cache
            now_session.pkts[Seq] = data
        
        if(Seq == now_session.waiting_pkt):
            while True:
                if now_session.isFinished():
                    break
                if len(now_session.pkts[now_session.waiting_pkt]) != 0:
                    now_session.waiting_pkt += 1
                else:
                    break
            ack_pkt = struct.pack("!HBBHHIIIQ", 52305,93, 4, HEADER_LEN, HEADER_LEN, 
                        0, now_session.waiting_pkt, chunkid, timestamp)
            print(f'chunkid: {chunkid}, ack: {now_session.waiting_pkt}.I send ack pkt to {from_addr}')
            sock.sendto(ack_pkt, from_addr)
        elif(Seq > now_session.waiting_pkt): # send duplicate ack
            ack_pkt = struct.pack("!HBBHHIIIQ", 52305,93, 4, HEADER_LEN, HEADER_LEN,
                         0, now_session.waiting_pkt, chunkid, timestamp)
            print(f'chunkid: {chunkid}, ack: {now_session.waiting_pkt}.I send ack pkt to {from_addr}----duplicate ack')
            sock.sendto(ack_pkt, from_addr)
        print()

        # see if the session is finished
        if now_session.isFinished():
            # global chunkhash_chunkdata
            chunkdata = now_session.getChunkData()
            chunkhash_chunkdata[chunkid_chunkhash[chunkid]] = chunkdata
            # 删除session
            del r_sessions[chunkid]

        # see if all chunks are downloaded
        if len(chunkhash_chunkdata) == len(chunkid_peer):
            # dump to output file
            with open(outputFile, "wb") as wf:
                pickle.dump(chunkhash_chunkdata, wf)
            # print GET message
            print(f"GET {outputFile}")

            # The following things are just for illustration, you do not need to print out in your design.
            sha1 = hashlib.sha1()
            sha1.update(chunkhash_chunkdata[bytes.hex(now_session.chunkhash)])
            received_chunkhash_str = sha1.hexdigest()
            print(f"Expected chunkhash: {bytes.hex(now_session.chunkhash)}")
            print(f"Received chunkhash: {received_chunkhash_str}")
            success = bytes.hex(now_session.chunkhash) == received_chunkhash_str
            print(f"Successful received: {success}")
            if success:
                print("Congrats! You have completed the example!")
            else:
                print("Example fails. Please check the example files carefully.")

    elif(Type == 4): # ACK
        print(f'chunkid: {chunkid}, Ack: {Ack}. I recevie ack pkt from {from_addr}')
        if chunkid not in s_sessions:
            return
        # get session
        now_session = s_sessions[chunkid]
        
        sampleRtt = time() - (timestamp / 1000000)
        print('sampleRtt:', sampleRtt)
        # update RTT if rtt is not set in cmd
        now_session.excuteRTT(sampleRtt)
        print('RTT:', now_session.RTT)

        chunkhash = chunkid_chunkhash[chunkid]
        if (Ack-1)*MAX_PAYLOAD >= CHUNK_DATA_SIZE: # finished
            print(f"finished sending {chunkhash}")
            del s_sessions[chunkid]
        else: # not finished
            if(Ack > now_session.sendBase): # send new data
                now_session.sendBase = Ack
                if(now_session.sendBase != now_session.nextPktNum):
                    now_session.open_timer()
                else:
                    now_session.close_timer()
                while now_session.nextPktNum <= now_session.sendBase+now_session.cwnd-1:
                    send_data = config.haschunks[chunkhash][(now_session.nextPktNum-1)*MAX_PAYLOAD: now_session.nextPktNum*MAX_PAYLOAD]
                    new_pkt = struct.pack("!HBBHHIIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data),
                            now_session.nextPktNum, 0, chunkid, int(round(time() * 1000000))) + send_data
                    print(f'chunkid: {chunkid}, seq = {now_session.nextPktNum}. I send data pkt to {from_addr} with payload: {bytes.hex(send_data)}')
                    if now_session.timer_start is None:
                        now_session.open_timer()
                    sock.sendto(new_pkt, from_addr)
                    now_session.nextPktNum += 1
            else: # duplicate ACKs
                now_session.duplicate_acks += 1
                if(now_session.duplicate_acks == 3):
                    # fast retransmit
                    send_data = config.haschunks[chunkhash][(now_session.sendBase-1)*MAX_PAYLOAD: now_session.sendBase*MAX_PAYLOAD]
                    retransmit_pkt = struct.pack("!HBBHHIIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data),
                            now_session.sendBase, 0, chunkid, int(round(time() * 1000000)))
                    print(f'chunkid: {chunkid}, seq = {now_session.sendBase}. I send data pkt to {from_addr} with payload: {bytes.hex(send_data)}')
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
            for chunkid, now_session in s_sessions.items():
                if now_session.isTimeout(): # timeout retransmit
                    now_session.updateTimeoutRTT()
                    print('retransmit RTT:', now_session.RTT)
                    chunkhash = bytes.hex(now_session.chunkhash)
                    send_data = config.haschunks[chunkhash][(now_session.sendBase-1)*MAX_PAYLOAD: now_session.sendBase*MAX_PAYLOAD]
                    retransmit_pkt = struct.pack("!HBBHHIIIQ", 52305,93, 3, HEADER_LEN, HEADER_LEN+len(send_data), 
                                    now_session.sendBase, 0, chunkid, int(round(time() * 1000000))) + send_data
                    print(f'chunkid: {chunkid}, seq: {now_session.sendBase}.I retransmit pkt to {now_session.peer_addr}')
                    now_session.open_timer()
                    sock.sendto(retransmit_pkt, now_session.peer_addr)
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
    preperation()
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
