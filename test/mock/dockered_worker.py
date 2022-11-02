# Built-in Imports
import threading
import queue
import logging
import platform

logger = logging.getLogger("chimerapy")

# Third-party
# Only import if linux
if platform.system() == "Linux":
    import docker


class LogThread(threading.Thread):
    def __init__(self, name: str, stream, output_queue: queue.Queue):
        super().__init__()

        # Saving input parameters
        self.name
        self.stream = stream
        self.output_queue = output_queue

    def __repr__(self):
        return f"<LogThread {self.name}>"

    def run(self):

        for data in self.stream:
            logger.debug(f"{self}: {data.decode()}")
            self.output_queue.put(data.decode())


class DockeredWorker:
    def __init__(self, client: docker.DockerClient, name: str):
        self.container = client.containers.run(
            image="chimerapy",
            auto_remove=False,
            stdin_open=True,
            detach=True,
            # network_mode="host", # Not realistic
        )
        self.name = name

    def connect(self, host, port):

        # Connect worker to Manager through entrypoint
        _, stream = self.container.exec_run(
            cmd=f"cp-worker --ip {host} --port {port} --name {self.name}", stream=True
        )

        # Execute worker connect
        self.output_queue = queue.Queue()
        self.log_thread = LogThread(self.name, stream, self.output_queue)
        self.log_thread.start()

        # # Wait until the connection is established
        while True:

            try:
                data = self.output_queue.get(timeout=10)
            except queue.Empty:
                raise RuntimeError("Connection failed")

            if "connected to Manager" in data:
                break

    def shutdown(self):

        # Then wait until the container is done
        self.container.kill()
        self.container.wait()