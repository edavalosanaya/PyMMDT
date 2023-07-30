import sys
import pickle
import asyncio
import enum
import logging
from typing import Dict, List

from aiohttp import web

from chimerapy.engine import config
from ..service import Service
from ..states import NodeState, WorkerState
from ..networking import Server
from ..networking.async_loop_thread import AsyncLoopThread
from ..networking.enums import NODE_MESSAGE
from ..utils import async_waiting_for
from ..eventbus import EventBus, Event, TypedObserver
from .events import (
    CreateNodeEvent,
    DestroyNodeEvent,
    ProcessNodeServerDataEvent,
    RegisteredMethodEvent,
    UpdateGatherEvent,
    UpdateResultsEvent,
    BroadcastEvent,
)


class HttpServerService(Service):
    def __init__(
        self,
        name: str,
        state: WorkerState,
        thread: AsyncLoopThread,
        eventbus: EventBus,
        logger: logging.Logger,
    ):

        # Save input parameters
        self.name = name
        self.state = state
        self.thread = thread
        self.eventbus = eventbus
        self.logger = logger

        # Containers
        self.tasks: List[asyncio.Task] = []

        # Create server
        self.server = Server(
            port=self.state.port,
            id=self.state.id,
            routes=[
                web.post("/nodes/create", self._async_create_node_route),
                web.post("/nodes/destroy", self._async_destroy_node_route),
                web.get("/nodes/server_data", self._async_report_node_server_data),
                web.post("/nodes/server_data", self._async_process_node_server_data),
                web.get("/nodes/gather", self._async_report_node_gather),
                web.post("/nodes/collect", self._async_collect),
                web.post("/nodes/step", self._async_step_route),
                web.post("/nodes/start", self._async_start_nodes_route),
                web.post("/nodes/record", self._async_record_route),
                web.post("/nodes/registered_methods", self._async_request_method_route),
                web.post("/nodes/stop", self._async_stop_nodes_route),
                web.post("/packages/load", self._async_load_sent_packages),
                web.post("/shutdown", self._async_shutdown_route),
            ],
            ws_handlers={
                NODE_MESSAGE.STATUS: self._async_node_status_update,
                NODE_MESSAGE.REPORT_GATHER: self._async_node_report_gather,
                NODE_MESSAGE.REPORT_RESULTS: self._async_node_report_results,
            },
            parent_logger=self.logger,
            thread=self.thread,
        )

        # Specify observers
        self.observers: Dict[str, TypedObserver] = {
            "start": TypedObserver("start", on_asend=self.start, handle_event="drop"),
            "shutdown": TypedObserver(
                "shutdown", on_asend=self.shutdown, handle_event="drop"
            ),
            "broadcast": TypedObserver(
                "broadcast",
                BroadcastEvent,
                on_asend=self._async_broadcast,
                handle_event="unpack",
            ),
        }
        for ob in self.observers.values():
            self.eventbus.subscribe(ob).result(timeout=1)

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://{self._ip}:{self._port}"

    async def start(self):

        # Runn the Server
        await self.server.async_serve()

        # Update the ip and port
        self._ip, self._port = self.server.host, self.server.port
        self.state.ip = self.ip
        self.state.port = self.port

        # After updatign the information, then run it!
        await self.eventbus.asend(Event("after_server_startup"))

    async def shutdown(self) -> bool:
        return await self.server.async_shutdown()

    ####################################################################
    ## Helper Functions
    ####################################################################

    async def _async_send(self, client_id: str, signal: enum.Enum, data: Dict) -> bool:
        return await self.server.async_send(
            client_id=client_id, signal=signal, data=data
        )

    async def _async_broadcast(self, signal: enum.Enum, data: Dict) -> bool:
        return await self.server.async_broadcast(signal=signal, data=data)

    def _create_node_server_data(self) -> Dict:

        # Construct simple data structure for Node to address information
        node_server_data = {"id": self.state.id, "nodes": {}}
        for node_id, node_state in self.state.nodes.items():
            node_server_data["nodes"][node_id] = {  # type: ignore[index]
                "host": self.state.ip,
                "port": node_state.port,
            }

        return node_server_data

    ####################################################################
    ## HTTP Routes
    ####################################################################

    async def _async_load_sent_packages(self, request: web.Request) -> web.Response:
        msg = await request.json()

        # For each package, extract it from the client's tempfolder
        # and load it to the sys.path
        for sent_package in msg["packages"]:

            # Wait until the sent package are started
            success = await async_waiting_for(
                condition=lambda: f"{sent_package}.zip"
                in self.server.file_transfer_records["Manager"],
                timeout=config.get("worker.timeout.package-delivery"),
            )

            if success:
                self.logger.debug(
                    f"{self}: Waiting for package {sent_package}: SUCCESS"
                )
            else:
                self.logger.error(f"{self}: Waiting for package {sent_package}: FAILED")
                return web.HTTPError()

            # Get the path
            package_zip_path = self.server.file_transfer_records["Manager"][
                f"{sent_package}.zip"
            ]["dst_filepath"]

            # Wait until the sent package is complete
            success = await async_waiting_for(
                condition=lambda: self.server.file_transfer_records["Manager"][
                    f"{sent_package}.zip"
                ]["complete"]
                is True,
                timeout=config.get("worker.timeout.package-delivery"),
            )

            if success:
                self.logger.debug(f"{self}: Package {sent_package} loading: SUCCESS")
            else:
                self.logger.debug(f"{self}: Package {sent_package} loading: FAILED")

            assert (
                package_zip_path.exists()
            ), f"{self}: {package_zip_path} doesn't exists!?"
            sys.path.insert(0, str(package_zip_path))

        # Send message back to the Manager letting them know that
        return web.HTTPOk()

    async def _async_create_node_route(self, request: web.Request) -> web.Response:
        msg_bytes = await request.read()

        # Create node
        node_config = pickle.loads(msg_bytes)
        await self.eventbus.asend(Event("create_node", CreateNodeEvent(node_config)))

        return web.HTTPOk()

    async def _async_destroy_node_route(self, request: web.Request) -> web.Response:
        msg = await request.json()

        # Destroy Node
        node_id = msg["id"]
        await self.eventbus.asend(Event("destroy_node", DestroyNodeEvent(node_id)))

        return web.HTTPOk()

    async def _async_report_node_server_data(
        self, request: web.Request
    ) -> web.Response:

        node_server_data = self._create_node_server_data()
        return web.json_response(
            {"success": True, "node_server_data": node_server_data}
        )

    async def _async_process_node_server_data(
        self, request: web.Request
    ) -> web.Response:
        msg = await request.json()

        # Broadcasting the node server data
        await self.eventbus.asend(
            Event("process_node_server_data", ProcessNodeServerDataEvent(msg))
        )

        return web.HTTPOk()

    async def _async_step_route(self, request: web.Request) -> web.Response:
        await self.eventbus.asend(Event("step"))
        return web.HTTPOk()

    async def _async_start_nodes_route(self, request: web.Request) -> web.Response:
        await self.eventbus.asend(Event("start_nodes"))
        return web.HTTPOk()

    async def _async_record_route(self, request: web.Request) -> web.Response:
        await self.eventbus.asend(Event("record"))
        return web.HTTPOk()

    async def _async_request_method_route(self, request: web.Request) -> web.Response:
        msg = await request.json()

        # Get event information
        event_data = RegisteredMethodEvent(
            node_id=msg["node_id"], method_name=msg["method_name"], params=msg["params"]
        )

        # Send it!
        await self.eventbus.asend(Event("registered_method", event_data))

        return web.HTTPOk()

    async def _async_stop_nodes_route(self, request: web.Request) -> web.Response:
        await self.eventbus.asend(Event("stop_nodes"))
        return web.HTTPOk()

    async def _async_report_node_gather(self, request: web.Request) -> web.Response:
        await self.eventbus.asend(Event("node_gather"))

        self.logger.warning(f"{self}: gather doesn't work ATM.")
        gather_data = {"id": self.state.id, "node_data": {}}
        return web.Response(body=pickle.dumps(gather_data))

    async def _async_collect(self, request: web.Request) -> web.Response:
        await request.json()

        # Collect data from the Nodes
        await self.eventbus.asend(Event("collect"))

        # After collecting, request to send the archive
        await self.eventbus.asend(Event("send_archive"))

        return web.HTTPOk()

    async def _async_shutdown_route(self, request: web.Request) -> web.Response:
        # Execute shutdown after returning HTTPOk (prevent Manager stuck waiting)
        self.tasks.append(asyncio.create_task(self.eventbus.asend(Event("shutdown"))))

        return web.HTTPOk()

    ####################################################################
    ## WS Routes
    ####################################################################

    async def _async_node_status_update(self, msg: Dict, ws: web.WebSocketResponse):

        # self.logger.debug(f"{self}: note_status_update: ", msg)
        node_state = NodeState.from_dict(msg["data"])
        node_id = node_state.id

        # Update our records by grabbing all data from the msg
        if node_id in self.state.nodes:
            self.state.nodes[node_id] = node_state

    async def _async_node_report_gather(self, msg: Dict, ws: web.WebSocketResponse):

        # Saving gathering value
        node_state = NodeState.from_dict(msg["data"]["state"])
        node_id = node_state.id

        if node_id in self.state.nodes:
            self.state.nodes[node_id] = node_state

        await self.eventbus.asend(
            Event(
                "update_gather",
                UpdateGatherEvent(
                    node_id=node_id, latest_value=msg["data"]["latest_value"]
                ),
            )
        )

    async def _async_node_report_results(self, msg: Dict, ws: web.WebSocketResponse):

        node_id = msg["data"]["node_id"]
        await self.eventbus.asend(
            Event(
                "update_results",
                UpdateResultsEvent(node_id=node_id, output=msg["data"]["output"]),
            )
        )
