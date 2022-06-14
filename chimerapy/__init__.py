# Adding the path of ChimeraPy to PATH
import os
import sys

# Path management
cwd = os.path.dirname(os.path.abspath(__file__))
sys.path.append(cwd)
log_file_path = os.path.join(cwd, 'logging_config.ini')

# Setup the logging for the library
# References: 
# https://docs.python-guide.org/writing/logging/
# https://stackoverflow.com/questions/13649664/how-to-use-logging-with-pythons-fileconfig-and-configure-the-logfile-filename
import logging.config

LOGGING_CONFIG = { 
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': { 
        'standard': { 
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': { 
        'default': { 
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',  # Default is stderr
        },
    },
    'loggers': { 
        '': {  # root logger
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False
        }
    } 
}

# Setup the logging configuration
logging.config.dictConfig(LOGGING_CONFIG)

# Level 2 imports
from chimerapy.core import Process, Pipeline, DataSource,\
    Sensor, Api

from chimerapy.utils import tools

# Level 3 imports
from chimerapy.core.tabular import TabularDataStream
from chimerapy.core.video import VideoDataStream

# For Sphinx docs
__all__ = [
    'TabularDataStream', 
    'VideoDataStream', 
    'Pipeline', 
    'DataSource',
    'Process',
    'Sensor',
    'tools',
]
