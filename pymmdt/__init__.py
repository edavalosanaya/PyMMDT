"""PyMMDT Package.

PyMMDT is a package that focus on multimodal data analytics and visualization.

Find our documentation at: https://edavalosanaya.github.io/PyMMDT/

"""

# Adding the path of PyMMDT to PATH
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Level 1 imports
from .runner import SingleRunner, GroupRunner
from .loader import Loader
from .logger import Logger
from .sorter import Sorter

# Level 2 imports
from . import core
