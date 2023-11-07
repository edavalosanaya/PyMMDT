import asyncio
from typing import Dict

import pytest

import chimerapy.engine as cpe
from chimerapy.engine.networking import Client
from chimerapy.engine.networking.enums import MANAGER_MESSAGE
from chimerapy.engine.states import ManagerState

from ..conftest import GenNode

logger = cpe._logger.getLogger("chimerapy-engine")


class Record:
    def __init__(self):
        self.network_state = None

    async def node_update_counter(self, msg: Dict):
        # logger.debug("Received node update message")
        self.network_state = ManagerState.from_dict(msg["data"])


@pytest.fixture
async def test_ws_client(manager):

    # Create a record
    record = Record()

    # Simulating a front-end client with a Python WS client
    client = Client(
        id="test_ws",
        host=manager.host,
        port=manager.port,
        ws_handlers={
            MANAGER_MESSAGE.NODE_STATUS_UPDATE: record.node_update_counter,
            MANAGER_MESSAGE.NETWORK_STATUS_UPDATE: record.node_update_counter,
        },
    )
    await client.async_connect()

    yield client, record
    await client.async_shutdown()


async def test_node_updates(test_ws_client, manager, worker):
    client, record = test_ws_client

    # Create original containers
    simple_graph = cpe.Graph()
    new_node = GenNode(name="Gen1")
    simple_graph.add_nodes_from([new_node])

    # Connect to the manager
    await worker.async_connect(host=manager.host, port=manager.port)
    # await manager.async_commit(simple_graph, mapping)
    await asyncio.sleep(3)
    assert record.network_state.to_json() == manager.state.to_json()


async def test_worker_network_updates(test_ws_client, manager, worker):
    client, record = test_ws_client

    # Connect to the manager
    await worker.async_connect(host=manager.host, port=manager.port)
    await asyncio.sleep(3)
    assert record.network_state.to_json() == manager.state.to_json()
    # logger.debug(record.network_state)
    # logger.debug(manager.state)

    await worker.async_deregister()
    await asyncio.sleep(3)
    # logger.debug(record.network_state)
    # logger.debug(manager.state)
    assert record.network_state.to_json() == manager.state.to_json()


async def test_reset_network_updates(test_ws_client, manager, worker):
    client, record = test_ws_client

    # Create original containers
    simple_graph = cpe.Graph()
    new_node = GenNode(name="Gen1")
    simple_graph.add_nodes_from([new_node])
    mapping = {worker.id: [new_node.id]}

    # Connect to the manager
    await worker.async_connect(host=manager.host, port=manager.port)
    await manager.async_commit(simple_graph, mapping)
    await asyncio.sleep(3)
    assert record.network_state.to_json() == manager.state.to_json()

    # Reset
    await manager.async_reset()
    await asyncio.sleep(3)
    assert record.network_state.to_json() == manager.state.to_json()

    # Recommit graph
    await manager.async_commit(simple_graph, mapping)
    await asyncio.sleep(3)
    assert record.network_state.to_json() == manager.state.to_json()