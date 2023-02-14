# Built-in Imports
import argparse

from .. import _logger

logger = _logger.getLogger("chimerapy")


def main():

    # Internal Imports
    from chimerapy.worker import Worker

    # Create the arguments for Worker CI
    parser = argparse.ArgumentParser(description="ChimeraPy Worker CI")

    # Adding the arguments
    parser.add_argument("--name", type=str, help="Name of the Worker", required=True)
    parser.add_argument("--ip", type=str, help="Manager's IP Address", required=True)
    parser.add_argument("--port", type=int, help="Manager's Port", required=True)
    parser.add_argument("--id", type=str, help="ID of the Worker", default=None)
    parser.add_argument("--wport", type=int, help="Worker's Port", default=8080)
    parser.add_argument(
        "--delete",
        type=bool,
        help="Delete Worker's data after transfer to Manager's computer",
        default=True,
    )

    args = parser.parse_args()

    # Convert the Namespace to a dictionary
    d_args = vars(args)

    # Create Worker and execute connect
    worker = Worker(name=d_args["name"], delete_temp=d_args["delete"], id=d_args["id"])
    worker.connect(host=d_args["ip"], port=d_args["port"])
    worker.idle()
    worker.shutdown()


if __name__ == "__main__":
    main()
