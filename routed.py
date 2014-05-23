#! /usr/local/bin/python
import sys
import re
import SocketServer
import socket
import select
import random
import time
import StringIO
import threading
from struct import *

# All the timer value in RIP spec
periodic_timer = 30
timeout_timer = 180
garbage_timer = 120

# Use a ratio of porpotional scale down all the timer for quick test
ratio = 10
t_timer = timeout_timer/ratio
g_timer = garbage_timer/ratio

def rand_p_timer():
    """ randomize periodic_timer to avoid packet sync jam the link"""
    return (periodic_timer + random.randrange(-5 , 5))/ratio

class Router(object):
    """
      Router class for group related methods and storage the routing table
    """
    def __init__(self, id):
        self.id = id
        self.route_table = {id:[0,id]} # routing for itself is 0

    def rip_request(self):
        """ generate a rip request payload """
        rip_header = pack('2bh', 1, 2, self.id) # set command version router id
        rip_rte =  pack('2h4i', 0, 0, 1234, 0, 0, 16) #set the request entry with afi =0 request for entire table
        payload_string = (rip_header + rip_rte).encode('hex')
        return payload_string

    def get_port(self, router_id):
        """ consulting the routing table for port of given router's id """
        for n in self.neighbours:
            if (n.id == router_id):
                return n.port

    def cal_route(self, dst, metric, next_hop):
        """ caluate the shortest route for dst and store in the routing table"""
        if dst in self.route_table:
            if(self.route_table[dst][0] > metric + self.route_table[next_hop][0]):
                self.route_table[dst][0] = metric + self.route_table[next_hop][0]
        else:
            self.route_table[dst] = [metric + self.route_table[next_hop][0], next_hop]

    def triggered_update(self, downid):
        """ genereate triggered"""
        for n in self.neighbours:
            rip_header = pack('2bh', 2, 2, self.id) # set command version and self router id
            rip_response = rip_header
            for router_id, metric in self.route_table.iteritems(): #generate all the RTEs
                if(n.id == router_id or downid == router_id): #split-horizon with posioned reverse
                    rte = pack('2h4i', 2, 0,  router_id, 0, 0, 16)
                else:
                    rte = pack('2h4i', 2, 0,  router_id, 0, 0, metric)
                rip_response = rip_response + rte
            payload_string = rip_response.encode('hex')
            socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socket.sendto(payload_string, ("localhost", n.port))
    def clean_record(self, downid):
        self.route_table.pop(downid, None)
        gctimers[downid].cancel()
        gctimers.pop(downid, None)
        self.triggered_update(downid)



    def rip_response(self, rid):
        """ genereate rip response"""
        rip_header = pack('2bh', 2, 2, self.id) # set command version and self router id
        rip_response = rip_header
        for router_id, metric in self.route_table.iteritems(): #generate all the RTEs
            if rid == router_id: #split-horizon with posioned reverse
                rte = pack('2h4i', 2, 0,  router_id, 0, 0, 16)
            else:
                rte = pack('2h4i', 2, 0,  router_id, 0, 0, metric[0])
            rip_response = rip_response + rte
        payload_string = rip_response.encode('hex')
        return payload_string
    def pretty_print(self):
        print "Router:" + str(self.id) +":"
        for router_id, metric in self.route_table.iteritems(): #generate all the RTEs
            print "to:" + str(router_id) + " takes:" + str(metric[0]) + " next:" + str(metric[0])

        print ""
class Neighbour(object):
    """ the router directly connected to it"""
    def __init__(self, id, metric, port):
        self.id = id
        self.metric = metric
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    def fileno(self):
        """ use for non-blocking IO """
        return self.socket.fileno()

class RouterHandler(SocketServer.BaseRequestHandler):
    """ event handler for incoming socket"""
    def handle(self):
        data = self.request[0] # payload
        socket = self.request[1] # socket fd
        body = data[8:] # get all the RTEs
        entries = len(body)/40 # find how many RTEs

        data_io = StringIO.StringIO(data) # use StringIO to process entries bytewise
        header =  data_io.read(8) # get header
        header_array = unpack('2bh', header.decode('hex')) # get the command version and router id into an array

        if(header_array[0] == 1): # if it's a request
            socket.sendto(router.rip_response(header_array[2]), ("localhost", router.get_port(header_array[2])))
        elif(header_array[0] == 2): # if it's a response
            for x in range(0, entries):
                rte = data_io.read(40)
                rte_array = unpack('2h4i', rte.decode('hex'))
                router.cal_route(rte_array[2], rte_array[5], header_array[2])
        if(timeouts.has_key(header_array[2])):
            timeouts[header_array[2]].cancel()
            timeouts.pop(header_array[2], None)
            if not (gctimers.has_key(header_array[2])):
                gctimers[header_array[2]] = threading.Timer(g_timer, router.clean_record,[header_array[2]])






def parse_config(f):
    """ parse configuration file"""
    for line in f:
        if re.search("router-id", line): # parse first line with router id
            m = re.findall(r"\d", line)
            router = Router(int(m[0]))
        elif re.search("input-ports", line): #parse second line with listeing ports
            router.listening_ports = []
            m = re.findall(r"\d+", line)
            for n in m:
                router.listening_ports.append(int(n))
        elif re.search("outputs", line): #parse third line with connected routers
            router.neighbours = []
            m = re.findall(r"\d+-\d+-\d+", line)
            for n in m:
                values = re.split("-", n)
                neighbour = Neighbour(int(values[2]), int(values[1]), int(values[0]))
                router.neighbours.append(neighbour)
                router.route_table[int(values[2])] = [int(values[1]),int(values[2])]

    return router


if __name__ == "__main__": # main program runs
    f = open(sys.argv[1], 'r') #first argument file name

    router = parse_config(f) #start parse config
    timeouts = {}
    gctimers = {}

    input_sockets = []
    # timers = {}
    for p in router.listening_ports:
        host, port = "localhost", p
        server = SocketServer.UDPServer((host, port), RouterHandler )
        input_sockets.append(server)


    running = 1
    while running: # entering a loop
        inputready, outputready, exceptready = select.select(input_sockets,router.neighbours,[]) # non-blocking IO
        for s in inputready:
            s.handle_request()

        for n in outputready: # for timer
            host, port = "localhost", n.port
            n.socket.sendto(router.rip_request(), (host, port))
            # if timers[n.id]:
            #     if timers[n.id].stopped:
            #         timers[n.id] = threading.Timer(t_timer, router.triggered_update) # trigger update
            if not(timeouts.has_key(n.id)):
                timeouts[n.id] = threading.Timer(t_timer, router.triggered_update, [n.id])
            router.pretty_print()
            p_timer = rand_p_timer()
            time.sleep(p_timer)




