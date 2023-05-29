# Built-in Imports
import time
import pathlib
import os

# Third-party

# Internal
import chimerapy as cp

logger = cp._logger.getLogger("chimerapy")
cp.debug()

# Constants
TEST_DIR = pathlib.Path(os.path.abspath(__file__)).parent
TEST_DATA_DIR = TEST_DIR / "data"


def test_manager_instance(manager):
    ...


def test_manager_instance_shutdown_twice(manager):
    manager.shutdown()


def test_worker_instance_shutdown_twice(worker):
    worker.shutdown()


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


def test_manager_shutting_down_gracefully():
    # While this one should not!

    # Create the actors
    manager = cp.Manager(logdir=TEST_DATA_DIR, port=0, enable_zeroconf=False)
    worker = cp.Worker(name="local", port=0)

    # Connect to the Manager
    worker.connect(method="ip", host=manager.host, port=manager.port)

    # Wait and then shutdown system through the manager
    worker.shutdown()
    manager.shutdown()


def test_manager_shutting_down_ungracefully():
    # While this one should not!

    # Create the actors
    manager = cp.Manager(logdir=TEST_DATA_DIR, port=0, enable_zeroconf=False)
    worker = cp.Worker(name="local", port=0)

    # Connect to the Manager
    worker.connect(method="ip", host=manager.host, port=manager.port)

    # Only shutting Manager
    manager.shutdown()
    worker.shutdown()


def test_zeroconf_connect(worker):

    manager = cp.Manager(logdir=TEST_DATA_DIR, port=0)

    worker.connect(method="zeroconf", blocking=False).result(timeout=30)
    assert worker.id in manager.workers

    manager.shutdown()
