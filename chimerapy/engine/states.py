import pathlib
from typing import Dict, Optional, Literal
from dataclasses import dataclass, field
from dataclasses_json import DataClassJsonMixin, cfg

from .eventbus import evented
from .node.registered_method import RegisteredMethod

# As https://github.com/lidatong/dataclasses-json/issues/202#issuecomment-1186373078
cfg.global_config.encoders[pathlib.Path] = str
cfg.global_config.decoders[pathlib.Path] = pathlib.Path  # is this necessary?


@dataclass
class NodeState(DataClassJsonMixin):
    id: str
    name: str = ""
    port: int = 0

    fsm: Literal[
        "NULL",
        "INITIALIZED",
        "CONNECTED",
        "READY",
        "PREVIEWING",
        "RECORDING",
        "STOPPED",
        "SAVED",
        "SHUTDOWN",
    ] = "NULL"

    registered_methods: Dict[str, RegisteredMethod] = field(default_factory=dict)


@dataclass
class WorkerState(DataClassJsonMixin):
    id: str
    name: str
    port: int = 0
    ip: str = ""
    nodes: Dict[str, NodeState] = field(default_factory=dict)


@evented
@dataclass
class ManagerState(DataClassJsonMixin):

    # General
    id: str = ""

    # Worker Handler Information
    workers: Dict[str, WorkerState] = field(default_factory=dict)

    # Http Server Information
    ip: str = ""
    port: int = 0

    # Distributed Logging information
    logs_subscription_port: Optional[int] = None
    log_sink_enabled: bool = False

    # Session logs
    logdir: pathlib.Path = pathlib.Path.cwd()