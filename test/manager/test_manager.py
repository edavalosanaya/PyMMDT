import time

import pytest

import chimerapy as cp
from ..conftest import GenNode, ConsumeNode, TEST_DATA_DIR

logger = cp._logger.getLogger("chimerapy")


def test_manager_instance(manager):
    ...


def test_manager_instance_shutdown_twice(manager):
    manager.shutdown()


def test_manager_registering_worker_locally(manager, worker):
    worker.connect(host=manager.host, port=manager.port)
    assert worker.id in manager.workers


def test_manager_registering_via_localhost(manager, worker):
    worker.connect(host="localhost", port=manager.port)
    assert worker.id in manager.workers


def test_manager_registering_workers_locally(manager):

    workers = []
    for i in range(3):
        worker = cp.Worker(name=f"local-{i}", port=0)
        worker.connect(method="ip", host=manager.host, port=manager.port)
        workers.append(worker)

    time.sleep(1)

    for worker in workers:
        assert worker.id in manager.workers
        worker.shutdown()


def test_zeroconf_connect(manager, worker):

    manager.zeroconf(enable=True)

    worker.connect(method="zeroconf", blocking=False).result(timeout=30)
    assert worker.id in manager.workers

    manager.zeroconf(enable=False)



def test_manager_shutting_down_gracefully():

    # Create the actors
    manager = cp.Manager(logdir=TEST_DATA_DIR, port=0)
    worker = cp.Worker(name="local", port=0)

    # Connect to the Manager
    worker.connect(method="ip", host=manager.host, port=manager.port)

    # Wait and then shutdown system through the manager
    worker.shutdown()
    manager.shutdown()



def test_manager_shutting_down_ungracefully():

    # Create the actors
    manager = cp.Manager(logdir=TEST_DATA_DIR, port=0)
    worker = cp.Worker(name="local", port=0)

    # Connect to the Manager
    worker.connect(method="ip", host=manager.host, port=manager.port)

    # Only shutting Manager
    manager.shutdown()
    worker.shutdown()


@pytest.mark.parametrize("context", ["multiprocessing", "threading"])
def test_manager_lifecycle(manager, worker, context):

    # Define graph
    gen_node = GenNode(name="Gen1")
    con_node = ConsumeNode(name="Con1")
    graph = cp.Graph()
    graph.add_nodes_from([gen_node, con_node])
    graph.add_edge(src=gen_node, dst=con_node)

    # Configure the worker and obtain the mapping
    worker.connect(host=manager.host, port=manager.port)
    mapping = {worker.id: [gen_node.id, con_node.id]}

    assert manager.start().result()

    time.sleep(3)

    assert manager.record().result()

    time.sleep(3)

    assert manager.stop().result()
    assert manager.collect().result()


def test_manager_reset(manager, worker):

    # Define graph
    gen_node = GenNode(name="Gen1")
    con_node = ConsumeNode(name="Con1")
    simple_graph = cp.Graph()
    simple_graph.add_nodes_from([gen_node, con_node])
    simple_graph.add_edge(src=gen_node, dst=con_node)

    # Configure the worker and obtain the mapping
    worker.connect(host=manager.host, port=manager.port)
    mapping = {worker.id: [gen_node.id, con_node.id]}

    manager.reset(keep_workers=True).result(timeout=30)

    manager.commit_graph(graph=simple_graph, mapping=mapping).result(timeout=30)
    assert manager.start().result()

    time.sleep(3)

    assert manager.record().result()

    time.sleep(3)
    
    assert manager.stop().result()
    assert manager.collect().result()


def test_manager_recommit_graph(worker, manager):

    # Define graph
    gen_node = GenNode(name="Gen1")
    con_node = ConsumeNode(name="Con1")
    simple_graph = cp.Graph()
    simple_graph.add_nodes_from([gen_node, con_node])
    simple_graph.add_edge(src=gen_node, dst=con_node)

    # Configure the worker and obtain the mapping
    worker.connect(host=manager.host, port=manager.port)
    mapping = {worker.id: [gen_node.id, con_node.id]}

    graph_info = {"graph": simple_graph, "mapping": mapping}

    logger.debug(f"STARTING COMMIT 1st ROUND")
    tic = time.time()
    assert manager.commit_graph(**graph_info).result(timeout=30)
    toc = time.time()
    delta = toc - tic
    logger.debug(f"FINISHED COMMIT 1st ROUND")

    logger.debug(f"STARTING RESET")
    assert manager.reset(keep_workers=True).result(timeout=30)
    logger.debug(f"FINISHED RESET")

    logger.debug(f"STARTING COMMIT 2st ROUND")
    tic2 = time.time()
    assert manager.commit_graph(**graph_info).result(timeout=30)
    toc2 = time.time()
    delta2 = toc2 - tic2
    logger.debug(f"FINISHED COMMIT 2st ROUND")

    # assert ((delta2 - delta) / (delta)) < 1

    manager.shutdown()
    worker.shutdown()
