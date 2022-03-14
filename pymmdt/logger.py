# Built-in Imports
from typing import Dict, Any
import multiprocessing as mp
import collections
import json
import pathlib
import time
import os
import queue

# Third-party imports
from PIL import Image
import numpy as np
import tqdm
import pandas as pd

# PyMMDT Library
from pymmdt.core.tools import get_memory_data_size
from .core.video import VideoEntry
from .core.tabular import TabularEntry, ImageEntry
from .base_process import BaseProcess

# Resource:
# https://stackoverflow.com/questions/8489684/python-subclassing-multiprocessing-process

class Logger(BaseProcess):

    def __init__(
            self,
            logdir:pathlib.Path,
            experiment_name:str,
            logging_queue:mp.Queue,
            message_to_queue:mp.Queue,
            message_from_queue:mp.Queue,
            verbose:bool=False
        ):
        super().__init__(
            message_to_queue=message_to_queue,
            message_from_queue=message_from_queue
        )

        # Save the input parameters
        self.logdir = logdir
        self.experiment_name = experiment_name
        self.experiment_dir = self.logdir / self.experiment_name
        self.logging_queue = logging_queue
        self.verbose = verbose

        # Keeping records of all logged data
        self.records = collections.defaultdict(dict)
        self.meta_data = {}
        self.dtype_to_class = {
            'tabular': TabularEntry,
            'image': ImageEntry,
            'video': VideoEntry
        }
        
        # Create the folder if it doesn't exist 
        if not self.logdir.exists():
            os.mkdir(self.logdir)

        # Create the experiment dir
        if not self.experiment_dir.exists():
            os.mkdir(self.experiment_dir)
        
        # Create a JSON file with the session's meta
        self.meta_data = {
            'id': self.experiment_name, 
            'subsessions': [], 
            'records': collections.defaultdict(dict)
        }
        self._save_meta_data()

        # Adding specific function class from the message
        self.subclass_message_to_functions.update({
        })

    def message_logging_status(self, data_chunk):

        # Create the message
        logging_status_message = {
            'header': 'UPDATE',
            'body': {
                'type': 'COUNTER',
                'content': {
                    'uuid': data_chunk['uuid'],
                    'num_of_logged_data': self.num_of_logged_data,
                }
            }
        }

        # Send the message
        try:
            self.message_from_queue.put(logging_status_message.copy(), timeout=0.5)
        except queue.Full:
            print("Logging_status_message failed to send!")

    def message_logger_finished(self):

        # Create the message
        logging_status_message = {
            'header': 'META',
            'body': {
                'type': 'END',
                'content': {}
            }
        }

        # Send the message
        try:
            self.message_from_queue.put(logging_status_message.copy(), timeout=0.5)
        except queue.Full:
            print("Logging_status_message failed to send!")
    
    def _save_meta_data(self):
        with open(self.experiment_dir / 'meta.json', "w") as json_file:
            json.dump(self.meta_data, json_file)
    
    def flush(self, data:Dict):
            
        # Detecting if this is the first time for the session
        if data['session_name'] not in self.records.keys() or data['name'] not in self.records[data['session_name']].keys():

            # New session processing (get the entry's directory)
            session_name = data['session_name']
            if session_name == 'root':
                entry_dir = self.experiment_dir

            else:# Add the new session to the subsesssions list
                if session_name not in self.meta_data['subsessions']:
                    self.meta_data['subsessions'].append(session_name)
                entry_dir = self.experiment_dir / session_name

            # Selecting the class
            entry_cls = self.dtype_to_class[data['dtype']]

            # Creating the entry and recording in meta data
            self.records[session_name][data['name']] = entry_cls(entry_dir, data['name'])
            entry_meta_data = {
                'dtype': data['dtype'],
                'start_time': str(data['data'].iloc[0]._time_),
                'end_time': str(data['data'].iloc[-1]._time_),
            }
            self.meta_data['records'][session_name][data['name']] = entry_meta_data
            self._save_meta_data()

            # Append the data to the new entry
            self.records[data['session_name']][data['name']].append(data)
            self.records[data['session_name']][data['name']].flush()

        # Not the first time
        else:

            # Test that the new data entry is valid to the type of entry
            assert isinstance(self.records[data['session_name']][data['name']], self.dtype_to_class[data['dtype']]), \
                f"Entry Type={self.records[data['session_name']][data['name']]} should match input data dtype {data['dtype']}"

            # Need to update the end_time for meta_data
            if len(data['data']) > 0:
                end_time_stamp = str(data['data'].iloc[-1]._time_)
                self.meta_data['records'][data['session_name']][data['name']]['end_time'] = end_time_stamp 
                self._save_meta_data()

            # If everything is good, add the change to the track history
            self.records[data['session_name']][data['name']].append(data)
            self.records[data['session_name']][data['name']].flush()

    def run(self):

        # Perform process setup
        self.setup()

        # Keeping track of processed data
        self.num_of_logged_data = 0

        # Continuously check if there are data to log and save
        while True: 

            # First check if there is an item in the queue
            if self.logging_queue.qsize() != 0:

                # Reporting
                if self.verbose:
                    ...

                # Get the data frome the queue and calculate the memory usage
                data_chunk = self.logging_queue.get(block=True)
                
                # Then process the data and tracking total
                self.flush(data_chunk)
                self.num_of_logged_data += 1
                self.message_logging_status(data_chunk)

            else:
                time.sleep(0.5)

            # Break Condition
            if self.thread_exit.is_set() and self.logging_queue.qsize() == 0:
                break

        # Sending message that the Logger finished!
        self.message_logger_finished()

        # Save all the entries and close!
        self.shutdown()
        self.close()

    def shutdown(self):

        # Then close all the entries
        for session in self.records.values():
            for entry in session.values():
                entry.close()
