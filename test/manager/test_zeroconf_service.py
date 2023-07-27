import asyncio
import logging

import pytest

from ..conftest import TEST_DATA_DIR
from chimerapy.engine.manager.zeroconf_service import ZeroconfService
from chimerapy.engine.manager.worker_handler_service import WorkerHandlerService
from chimerapy.engine.networking.async_loop_thread import AsyncLoopThread
from chimerapy.engine.eventbus import EventBus, configure
from chimerapy.engine.states import ManagerState

logger = logging.getLogger("chimerapy-engine")

from zeroconf import Zeroconf, ServiceInfo, ServiceListener, ServiceBrowser
import zeroconf


class MockZeroconfListener(ServiceListener):
    def __init__(
        self,
        stop_service_name: str = None,
    ):
        # Saving input parameters
        self.stop_service_name = stop_service_name
        self.is_service_found = False
        self.service_info: zeroconf._services.info.ServiceInfo = {}

    def update_service(self, *args, **kwargs):
        """Mandatory method, but can be empty"""
        ...

    def remove_service(self, *args, **kwargs):
        """Mandatory method, but can be empty"""
        ...

    def add_service(self, zeroconf, type, name):
        """Add detected services and stop if ``chimerapy-engine`` detected!"""
        info = zeroconf.get_service_info(type, name)

        if isinstance(info, ServiceInfo):
            if self.stop_service_name and name.startswith(self.stop_service_name):
                logger.info(f"chimerapy-engine zeroconf service detected: {info}")
                self.is_service_found = True
                self.service_info = info

@pytest.fixture
def zeroconf_service():
    
    thread = AsyncLoopThread()
    thread.start()
    eventbus = EventBus()
    configure(eventbus, thread)

    state = ManagerState()

    zeroconf_service = ZeroconfService('zeroconf', eventbus, state)
    zeroconf_service.start()
    return zeroconf_service

@pytest.mark.asyncio
async def test_enable_and_disable_zeroconf(zeroconf_service):

    assert await zeroconf_service.enable()
    await asyncio.sleep(1)
    assert await zeroconf_service.disable()


@pytest.mark.asyncio
async def test_zeroconf_connect(zeroconf_service):

    assert await zeroconf_service.enable()
    await asyncio.sleep(1)

    # Create the Zeroconf instance and the listener
    zeroconf = Zeroconf()
    listener = MockZeroconfListener(
        stop_service_name="chimerapy"
    )

    # Browse for services
    browser = ServiceBrowser(zeroconf, "_http._tcp.local.", listener)

    # Wait
    await asyncio.sleep(5)

    # Clean up
    browser.cancel()
    zeroconf.close()

    # Then perform the asserts
    assert listener.is_service_found
    assert await zeroconf_service.disable()
