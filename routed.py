#! /usr/local/bin/python
import sys
import re
import SocketServer
import socket
import select
import random
import time

periodic_timer = 30
timeout_timer = 180
garbage_timer = 120
ratio = 10

t_timer = timeout_timer/ratio
g_timer = garbage_timer/ratio

def rand_p_timer():
    return (periodic_timer + random.randrange(-5 , 5))/ratio

class Router(object):
    def __init__(self, id):
        self.id = id

class RouterHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        print data
        socket.sendto("hello", self.client_address)


class Neighbour(object):
    def __init__(self, id, metric, port):
        self.id = id
        self.metric = metric
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    def fileno(self):
        return self.socket.fileno()



def parse_config(f):
    for line in f:
        if re.search("router-id", line):
            m = re.findall(r"\d", line)
            router = Router(m[0])
        elif re.search("input-ports", line):
            router.listening_ports = []
            m = re.findall(r"\d+", line)
            for n in m:
                router.listening_ports.append(int(n))
        elif re.search("outputs", line):
            router.neighbours = []
            m = re.findall(r"\d+-\d+-\d+", line)
            for n in m:
                values = re.split("-", n)
                neighbour = Neighbour(int(values[2]), int(values[1]), int(values[0]))
                router.neighbours.append(neighbour)
    return router


if __name__ == "__main__":
    f = open(sys.argv[1], 'r')
    router = parse_config(f)

    input_sockets = []
    for p in router.listening_ports:
        host, port = "localhost", p
        server = SocketServer.UDPServer((host, port), RouterHandler )
        input_sockets.append(server)

    # output_sockets = []
    # for n in router.neighbours:
    #     output_sockets.append(s)

running = 1
while running:
    inputready, outputready, exceptready = select.select(input_sockets,router.neighbours,[])
    for s in inputready:
        s.handle_request()

    for n in outputready:
        host, port = "localhost", n.port
        n.socket.sendto("From: "+ str(router.id)+"To: " + str(n.id) + "metric: " + str(n.metric), (host, port))
        p_timer = rand_p_timer()
        time.sleep(p_timer)
        print str(p_timer) + "Has passed"




