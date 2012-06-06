import uuid, random
import zmq
from zmq.eventloop.zmqstream import ZMQStream
import paramiko
import os

class TrustedMultiKernelManager:
    """A class for managing multiple kernels on the trusted side."""

    def __init__(self):

        self._kernels = {} #kernel_id: {"comp_id": comp_id, "ports": {"hb_port": hb, "iopub_port": iopub, "shell_port": shell, "stdin_port": stdin}}
        self._comps = {} #comp_id: {"host", "", "port": ssh_port, "kernels": {}, "max": #, "beat_interval": Float, "first_beat": Float}
        self._clients = {} #comp_id: zmq req socket object
        
        self.context = zmq.Context()

    def get_kernel_ids(self, comp = None):
        ids = []
        if comp is not None and comp in self._comps:
            ids = self._comps[comp]["kernels"].keys()
        else:
            ids = self._kernels.keys()
        return ids

    def get_hb_info(self, kernel_id):
        comp_id = self._kernels[kernel_id]["comp_id"]
        comp = self._comps[comp_id]
        return (comp["beat_interval"], comp["first_beat"])

    def setup_initial_comps(self):
        """ Tries to read a config file containing initial computer information """
        tmp_comps = {}

        try:
            import config
        except:
            config = object()

        defaults = {"max": 10, "beat_interval": 3.0, "first_beat": 5.0}

        if hasattr(config, "computers"):
            for i in config.computers:
                i["kernels"] = {}
                comp_id = str(uuid.uuid4())
                x = dict(defaults.items() + i.items())
                tmp_comps[comp_id] = x
                context = zmq.Context()
                req = context.socket(zmq.REQ)
                port = req.bind_to_random_port("tcp://127.0.0.1")
                client = self.setup_ssh_connection(x["host"],x["username"])
                client.exec_command("python '%s/receiver.py' %d" % (os.getcwd(), port))
                req.send("")
                if(req.recv() == "handshake"):
                    self._clients[comp_id] = req
                    print "ZMQ Connection with computer %s at port %d established." %(comp_id, port)
                
        self._comps = tmp_comps

    def setup_ssh_connection(self, host, username):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, username=username)
        return ssh

    def purge_kernels(self, comp_id):
        """ Kills all kernels on a given computer. """
        req = self._clients[comp_id]
        req.send("purge_kernels")
        print req.recv()

    def add_computer(self, config):
        """ Adds a tracked computer. """
        comp_id = uuid.uuid4()
        self._comps[comp_id] = config

    def remove_computer(self, comp_id):
        """ Removes a tracked computer. """
        self.purge_kernels(comp_id)
        del self._comps[comp_id]

    def new_session(self):
        """Starts a new kernel on an open computer."""
        comp_id = self._find_open_computer()
        
        req = self._clients[comp_id]
        req.send("start_kernel")
        
        x = req.recv_pyobj()
        kernel_id=x["kernel_id"]
        kernel_ports=x["ports"]

        self._kernels[kernel_id] = {"comp_id": comp_id, "ports": kernel_ports}
        self._comps[comp_id]["kernels"][kernel_id] = None
        #print "Kernels ::: ", self._kernels
        return kernel_id

    def end_session(self, kernel_id):
        """Kills an existing kernel on a given computer."""
        comp_id = self._kernels[kernel_id]["comp_id"]

        req = self._clients[comp_id]
        req.send("kill_kernel")
        print "Killing Kernel ::: %s at %s"%(kernel_id, (comp_id))
        req.recv()
        req.send(kernel_id)
        status = req.recv_pyobj()
        
        if (status):
            del self._kernels[kernel_id]
            del self._comps[comp_id]["kernels"][kernel_id]
        else:
            print "error ending kernel"
        
    def _find_open_computer(self):
        """Returns the comp_id of a computer able to start a new kernel."""
        
        ids = self._comps.keys()
        random.shuffle(ids)
        found_id = None
        done = False
        index = 0        

        while (index < len(ids) - 1 and not done):
            found_id = ids[index]
            if len(self._comps[found_id]["kernels"].keys()) < self._comps[found_id]["max"]:
                done = True
            else:
                index += 1
        if done:
            return found_id
        else:
            raise IOError("Could not find open computer. There are %d computers available."%len(ids))

    def _create_connected_stream(self, host, port, socket_type):
        sock = self.context.socket(socket_type)
        addr = "tcp://%s:%i" % (host, port)
        print "Connecting to: %s" % addr
        sock.connect(addr)
        return ZMQStream(sock)
    
    def create_iopub_stream(self, kernel_id):
        comp_id = self._kernels[kernel_id]["comp_id"]
        host = self._comps[comp_id]["host"]
        ports = self._kernels[kernel_id]["ports"]
        iopub_stream = self._create_connected_stream(host, ports["iopub_port"], zmq.SUB)
        iopub_stream.socket.setsockopt(zmq.SUBSCRIBE, b"")
        return iopub_stream

    def create_shell_stream(self, kernel_id):
        comp_id = self._kernels[kernel_id]["comp_id"]
        host = self._comps[comp_id]["host"]
        ports = self._kernels[kernel_id]["ports"]
        shell_stream = self._create_connected_stream(host, ports["shell_port"], zmq.DEALER)
        return shell_stream

    def create_hb_stream(self, kernel_id):
        comp_id = self._kernels[kernel_id]["comp_id"]
        host = self._comps[comp_id]["host"]
        ports = self._kernels[kernel_id]["ports"]
        hb_stream = self._create_connected_stream(host, ports["hb_port"], zmq.REQ)
        return hb_stream

""" TO DO:

* SSH connecting to the UMKM
* Have the TMKM manage / start / stop connections from the kernel < -- > server

"""

from time import sleep
if __name__ == "__main__":
    trutest = TrustedMultiKernelManager()

    trutest.setup_initial_comps()

    for i in xrange(5):
        test_id = trutest.new_session()
        #trutest.end_session(test_id)

    vals = trutest._comps.values()
    for i in xrange(len(vals)):
        print "\nComputer #%d has kernels ::: "%i, vals[i]["kernels"].keys()

    print "\nList of all kernel ids ::: " + str(trutest.get_kernel_ids())
        


    y=trutest._clients.keys()
    for i in y:
        trutest.purge_kernels(i)

