from typing import Union, Optional
import time
import json

import dill
import requests
import pytest
import chimerapy as cp

logger = cp._logger.getLogger("chimerapy")


class NodeWithRegisteredMethods(cp.Node):
    def __init__(
        self, name: str, init_value: int = 0, debug_port: Optional[int] = None
    ):
        super().__init__(name=name, debug_port=debug_port)
        self.init_value = init_value

    def setup(self):
        self.logger.debug(f"{self}: executing PREP")
        self.value = self.init_value

    def step(self):
        time.sleep(0.5)
        self.value += 1
        return self.value

    def teardown(self):
        self.logger.debug(f"{self}: executing TEARDOWN")

    # Default style
    @cp.register
    async def printout(self):
        self.logger.debug(f"{self}: logging out value: {self.value}")
        return self.value

    # Style: blocking
    @cp.register.with_config(params={"value": "Union[int, float]"}, style="blocking")
    async def set_value(self, value: Union[int, float]):
        self.value = value
        return value

    # Style: Reset
    @cp.register.with_config(style="reset")
    async def reset(self):
        self.init_value = 100
        return 100


@pytest.fixture
def node_with_reg_methods(logreceiver):
    return NodeWithRegisteredMethods(name="RegNode1", debug_port=logreceiver.port)


@pytest.fixture
def worker_with_reg(worker, node_with_reg_methods):

    # Simple single node without connection
    msg = {
        "id": node_with_reg_methods.id,
        "name": node_with_reg_methods.name,
        "pickled": dill.dumps(node_with_reg_methods),
        "in_bound": [],
        "in_bound_by_name": [],
        "out_bound": [],
        "follow": None,
    }

    logger.debug("Create nodes")
    worker.create_node(msg).result(timeout=30)

    logger.debug("Start nodes!")
    worker.start_nodes().result(timeout=5)

    return worker


@pytest.fixture
def single_node_with_reg_methods_manager(manager, worker, node_with_reg_methods):

    # Define graph
    simple_graph = cp.Graph()
    simple_graph.add_nodes_from([node_with_reg_methods])

    # Connect to the manager
    worker.connect(method="ip", host=manager.host, port=manager.port)

    # Then register graph to Manager
    assert manager.commit_graph(
        simple_graph,
        {
            worker.id: [node_with_reg_methods.id],
        },
    )

    return manager


def test_registered_method_with_concurrent_style(
    worker_with_reg, node_with_reg_methods
):

    # Execute the registered method (with config)
    logger.debug("MAKING THE REQUEST TO EXECUTE REGISTERED METHOD")
    results = worker_with_reg.request_registered_method(
        node_with_reg_methods.id, "printout"
    ).result(timeout=10)
    assert (
        results["success"]
        and isinstance(results["output"], int)
        and results["output"] >= 0
    )


def test_registered_method_with_params_and_blocking_style(
    worker_with_reg, node_with_reg_methods
):

    # Execute the registered method (with config)
    r = requests.post(
        f"http://{worker_with_reg.ip}:{worker_with_reg.port}"
        + "/nodes/registered_methods",
        json.dumps(
            {
                "node_id": node_with_reg_methods.id,
                "method_name": "set_value",
                "timeout": 10,
                "params": {"value": -100},
            }
        ),
    )
    assert r.status_code == requests.codes.ok
    msg = r.json()
    assert msg["success"] and msg["return"] == -100

    # Make sure the system works after the request
    time.sleep(2)


def test_registered_method_with_reset_style(worker_with_reg, node_with_reg_methods):

    # Execute the registered method (without config and params)
    r = requests.post(
        f"http://{worker_with_reg.ip}:{worker_with_reg.port}"
        + "/nodes/registered_methods",
        json.dumps(
            {
                "node_id": node_with_reg_methods.id,
                "method_name": "reset",
                "timeout": 10,
                "params": {},
            }
        ),
    )
    assert r.status_code == requests.codes.ok
    msg = r.json()
    assert msg["success"] and msg["return"] == 100

    # Make sure the system works after the request
    time.sleep(2)


def test_manager_requesting_registered_methods(
    single_node_with_reg_methods_manager, node_with_reg_methods
):
    single_node_with_reg_methods_manager.start()
    time.sleep(2)
    assert single_node_with_reg_methods_manager.request_registered_method(
        node_id=node_with_reg_methods.id, method_name="printout", timeout=10
    )
    time.sleep(2)
    assert single_node_with_reg_methods_manager.request_registered_method(
        node_id=node_with_reg_methods.id,
        method_name="set_value",
        timeout=10,
        params={"value": -100},
    )
    time.sleep(2)
    assert single_node_with_reg_methods_manager.request_registered_method(
        node_id=node_with_reg_methods.id, method_name="reset", timeout=10
    )
    time.sleep(2)
