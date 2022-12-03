# Setup the logging for the library
# References:
# https://docs.python-guide.org/writing/logging/
# https://stackoverflow.com/questions/13649664/how-to-use-logging-with-pythons-fileconfig-and-configure-the-logfile-filename
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "formatter": "standard",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",  # Default is stderr
        },
        "datagram": {
            "level": "INFO",
            "formatter": "standard",
            "class": "logging.handlers.DatagramHandler",
            "host": "127.0.0.1",
            "port": 5555,
        },
    },
    "loggers": {
        "chimerapy": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "chimerapy-networking": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "chimerapy-subprocess": {
            "handlers": ["datagram"],
            "level": "INFO",
            "propagate": True,
        },
    },
}

# Setup the logging configuration
def setup():
    logging.config.dictConfig(LOGGING_CONFIG)
