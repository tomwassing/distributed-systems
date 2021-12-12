import threading
import random
import pytest
from follower import Follower
from leader import Leader
from client import Client


def setup(num_nodes, num_clients, start_port=25000):

    node_ports = list(range(start_port, start_port + num_nodes))
    node_hosts = [("127.0.0.1", port) for port in node_ports]
    nodes = [Follower(("127.0.0.1", port), [h for h in node_hosts if h[1] != port], node_hosts[-1]) for port in node_ports[:-1]]
    leader = Leader(node_hosts[-1], node_hosts[:-1], node_hosts[-1])
    threads = [threading.Thread(target=node.run) for node in [leader, *nodes]]
    clients = [Client(node_hosts) for _ in range(num_clients)]

    for thread in threads:
        thread.start()

    return node_hosts, nodes, leader, clients, threads

def setup_delay(num_nodes, num_clients, start_port=25000):
    node_ports = list(range(start_port, start_port + num_nodes))
    node_hosts = [("127.0.0.1", port) for port in node_ports]
    nodes = [Follower(port, [h for h in node_hosts if h[1] != port], node_hosts[-1]) for port in node_ports[:-1]]
    leader = Leader(node_hosts[-1][1], node_hosts[:-1], node_hosts[-1])

    threads = []
    for i, node in enumerate([leader, *nodes]):
        if i == 1:
            threads.append(threading.Thread(target=node.run_delayed))
        else:
            threads.append(threading.Thread(target=node.run))

    clients = [Client(node_hosts) for _ in range(num_clients)]

    for thread in threads:
        thread.start()

    return node_hosts, nodes, leader, clients, threads

class TestSimpleTest:
    def setup_method(self, method):
        _, nodes, leader, clients, threads = setup(3, 5)
        self.nodes = nodes
        self.leader = leader
        self.clients = clients
        self.threads = threads

    def teardown_method(self):
        for client in self.clients:
            client.exit()
        for thread in self.threads:
            thread.join()

    @pytest.mark.parametrize('execution_number', range(10))
    def test_read_after_write(self, execution_number):
        client = self.clients[0]
        client.write("World!", 'Hello?')
        read_value = client.read('World!')["value"]
        order_index = client.read('World!')["order_index"]

        assert read_value == 'Hello?' and order_index == 0

    @pytest.mark.parametrize('execution_number', range(10))
    def test_read_after_five_writes(self, execution_number):
        client = self.clients[0]
        client2 = self.clients[1]
        client.write("World!", 'Hello1?')
        client2.write("World!", 'Hello2?')
        client.write("World!", 'Hello3?')
        client2.write("World!", 'Hello4?')
        client.write("World!", 'Hello5?')

        read_value = client.read('World!')["value"]
        order_index = client.read('World!')["order_index"]

        assert read_value == 'Hello5?' and order_index == 4

    @pytest.mark.parametrize('execution_number', range(10))
    def test_multi_sync(self, execution_number):
        client = self.clients[0]
        for i in range(100):
            client.write("World!", "Hello{}?".format(i))

        read_value = client.read('World!')["value"]
        order_index = client.read('World!')["order_index"]

        assert read_value == 'Hello99?' and order_index == 99

    @pytest.mark.parametrize('execution_number', range(10))
    def test_write_read_different_client(self, execution_number):
        write_client, read_client = random.sample(self.clients, 2)
        write_client.write("World!", 'Hello')

        assert read_client.read('World!')["value"] == 'Hello'

class TestDurability:

    def setup_method(self, method):
        node_hosts, nodes, leader, clients, threads = setup(5, 2)
        self.node_hosts = node_hosts
        self.nodes = nodes
        self.leader = leader
        self.clients = clients
        self.threads = threads

    def teardown_method(self):
        for client in self.clients:
            client.exit()
        for thread in self.threads:
            thread.join()

    @pytest.mark.parametrize('execution_number', range(10))
    def test_fe1(self, execution_number):
        values = []
        client = self.clients[0]
        client.write("World!", 'Hello?')
        for host in self.node_hosts:
            values.append(client.read('World!', host=host)["value"])

        assert len(set(values)) == 1

    @pytest.mark.parametrize('execution_number', range(10))
    def test_fe2(self, execution_number):
        values = []
        client = self.clients[0]
        client.write("World!", 'Hello?')
        for host in self.node_hosts:
            values.append(client.read('World!', host=host)["value"])

        if len(set(values)) == 1:
            client.write("World!", 'Bye!')

            values = []
            for host in self.node_hosts:
                values.append(client.read('World!', host=host)["value"])

            assert len(set(values)) == 1 and list(set(values))[0] == 'Bye!'

    @pytest.mark.parametrize('execution_number', range(10))
    def test_fe3(self, execution_number):
        values = []
        client = self.clients[0]
        read_client = self.clients[1]
        for i in range(100):
            client.write("World!", "Hello{}?".format(i), blocking=False)

        for i in range(100):
            tmp = client.write_recv()

        for host in self.node_hosts:
            values.append(read_client.read('World!', host=host)["value"])

        assert len(set(values)) == 1

class TestConsistency:

    def setup_method(self, method):
        node_hosts, nodes, leader, clients, threads = setup(5, 4)
        self.node_hosts = node_hosts
        self.nodes = nodes
        self.leader = leader
        self.clients = clients
        self.threads = threads

    def teardown_method(self):
        for client in self.clients:
            client.exit()
        for thread in self.threads:
            thread.join()

    @pytest.mark.parametrize('execution_number', range(10))
    def test_multi_async_single_client(self, execution_number):
        values = []
        client = self.clients[0]
        for i in range(100):
            client.write("World!", "Hello{}?".format(i), blocking=False)

        for i in range(100):
            client.write_recv()

        for host in self.node_hosts:
            values.append((client.read('World!', host=host)["value"], client.read('World!', host=host)["order_index"]))

        value_set = set(values)
        length = len(value_set)
        if length == 1:
            order_index = value_set.pop()

            assert order_index[1] == 99

    @pytest.mark.parametrize('execution_number', range(10))
    def test_multi_async_multi_client(self, execution_number):
        values = []
        clients = [self.clients[x] for x in range(4)]
        for i in range(100):
            client = clients[i%4]
            client.write("World!", "Hello{}?".format(i), blocking=False)

        for i in range(100):
            client = clients[i%4]
            client.write_recv()

        for host in self.node_hosts:
            values.append((client.read('World!', host=host)["value"], client.read('World!', host=host)["order_index"]))

        value_set = set(values)
        length = len(value_set)
        if length == 1:
            order_index = value_set.pop()

            assert order_index[1] == 99


class TestConsistency_delay:

    def setup_method(self, method):
        # node_ports, nodes, leader, clients, processes = setup_delay(5, 4)
        # self.node_ports = node_ports
        # self.nodes = nodes
        # self.leader = leader
        # self.clients = clients
        # self.processes = processes

        node_hosts, nodes, leader, clients, threads = setup_delay(5, 4)
        self.node_hosts = node_hosts
        self.nodes = nodes
        self.leader = leader
        self.clients = clients
        self.threads = threads

    def teardown_method(self):
        for client in self.clients:
            client.exit()
        for thread in self.threads:
            thread.join()


    @pytest.mark.parametrize('execution_number', range(1))
    def test_out_of_order(self, execution_number):
        values = []
        client = self.clients[0]
        print(self.node_hosts)
        for i in range(5):
            if i == 2:
                client.write("World!", f"Hello{i}?", host=self.node_hosts[0], blocking=False)
            else:
                client.write("World!", f"Hello{i}?", host=self.node_hosts[1], blocking=False)
        for i in range(5):
            client.write_recv()

        for host in self.node_hosts:
            values.append((client.read('World!', host=host)["value"], client.read('World!', host=host)["order_index"]))

        value_set = set(values)
        length = len(value_set)
        if length == 1:
            order_index = value_set.pop()
            assert order_index[1] == 4 and order_index[0] == 'Hello2?'