# Resource:
# https://stackoverflow.com/questions/64505389/cant-reference-existing-qml-elements-from-python

# Built-in Imports
from typing import Optional, List, Dict, Sequence
import os
import sys
import datetime
import pathlib
import json
import collections
import queue
import threading
import time
import multiprocessing as mp
import multiprocessing.managers as mpm

# Third-party Imports
import numpy as np
import pandas as pd
import tqdm
import psutil

# Setting pandas to stop annoying warnings
pd.options.mode.chained_assignment = None

# PyQt5 Imports
from PyQt5.QtCore import QTimer, QObject, pyqtProperty, pyqtSignal, pyqtSlot

# Interal Imports
from .dashboard_model import DashboardModel
from .timetrack_model import TimetrackModel
from .sliding_bar_object import SlidingBarObject
from .pausable_timer import QPausableTimer
from .loading_bar_object import LoadingBarObject

# PyMMDT Library Imports
from pymmdt.loader import Loader
from pymmdt.sorter import Sorter
from pymmdt.core.tools import clear_queue, threaded, get_windows
from pymmdt.core.data_stream import DataStream
from pymmdt.core.video.data_stream import VideoDataStream
from pymmdt.core.tabular.data_stream import TabularDataStream

class Manager(QObject):
    modelChanged = pyqtSignal()
    playPauseChanged = pyqtSignal()
    pageChanged = pyqtSignal()
    dataLoadedChanged = pyqtSignal()
    slidingBarChanged = pyqtSignal()

    signals = [modelChanged, playPauseChanged, pageChanged, dataLoadedChanged]

    def __init__(
            self,
            logdir:str,
            loading_sec_limit:int=5,
            time_step:int=100,
            replay_speed:int=1,
            time_window:pd.Timedelta=pd.Timedelta(seconds=1),
            meta_check_step:int=5000,
            max_message_queue_size:int=1000,
            max_loading_queue_size:int=1000,
            memory_limit:float=0.8,
            loader_memory_ratio:float=0.1,
            verbose:bool=False,
        ):
        super().__init__()

        # Store the CI arguments
        self.logdir = pathlib.Path(logdir)
        self.loading_sec_limit = loading_sec_limit
        self.time_step: int = time_step # milliseconds
        self.replay_speed = replay_speed
        self.time_window = time_window
        self.meta_check_step = meta_check_step # milliseconds
        self.max_message_queue_size = max_message_queue_size
        self.max_loading_queue_size = max_loading_queue_size
        self.verbose = verbose

        # Keeping track of all the data in the logdir
        self._page = "homePage"
        self.logdir_records = None

        # Creating the used dashboard model
        self._dashboard_model = DashboardModel()
        self._timetrack_model = TimetrackModel()
        self._sliding_bar = SlidingBarObject()
        self._loading_bar = LoadingBarObject()
        self._sorting_bar = LoadingBarObject()
        
        # Parameters for tracking progression
        self.timetrack = None
        self.current_time = pd.Timedelta(seconds=0)
        self.current_window = 0
        self.windows: List = []
        self.loaded_windows: List = []

        # Keeping track of memory usage
        self.loader_memory_ratio = loader_memory_ratio
        self.total_available_memory = memory_limit * psutil.virtual_memory().available
        self.loading_queue_memory_chunks = {}
        self.sorting_queue_memory_chunks = {}
        self.total_memory_used = 0
        
        # Closing information
        self.thread_exit = threading.Event()
        self.thread_exit.clear()

        # Keeping track of the pause/play state and the start, end time
        self.stop_everything = False
        self._data_is_loaded = False
        self._is_play = False
        self.end_time = pd.Timedelta(seconds=0)
        self.session_complete = False

        # Apply the update to the meta data
        self.meta_update()

        # Using a timer to periodically update content
        # self.current_time_update = QPausableTimer()
        # self.current_time_update.setInterval(self.time_step)
        # self.current_time_update.timeout.connect(self.update_content)
        # self.current_time_update.start()

        # Using a timer to periodically check for new data
        self.meta_check_timer = QTimer()
        self.meta_check_timer.setInterval(self.meta_check_step) 
        self.meta_check_timer.timeout.connect(self.meta_update)
        self.meta_check_timer.start()
        
        # Define the protocol for processing messages from the loader and logger
        self.respond_message_protocol = {
            'LOADER':{
                'UPDATE': {
                    'TIMETRACK': self.respond_loader_message_timetrack,
                    'COUNTER': self.respond_loader_message_counter
                },
                'META': {
                    'END': self.respond_loader_message_end
                }
            },
            'SORTER':{
                'UPDATE': {
                    'COUNTER': self.respond_sorter_message_counter,
                    'MEMORY': self.respond_sorter_message_memory
                },
                'META': {
                    'END': self.respond_sorter_message_end
                }
            }
        }

    @pyqtProperty(str, notify=pageChanged)
    def page(self):
        return self._page

    @pyqtProperty(DashboardModel, notify=modelChanged)
    def dashboard_model(self):
        return self._dashboard_model

    @pyqtProperty(TimetrackModel, notify=modelChanged)
    def timetrack_model(self):
        return self._timetrack_model

    @pyqtProperty(SlidingBarObject)
    def sliding_bar(self):
        return self._sliding_bar

    @pyqtProperty(LoadingBarObject)
    def loading_bar(self):
        return self._loading_bar

    @pyqtProperty(LoadingBarObject)
    def sorting_bar(self):
        return self._sorting_bar

    @pyqtProperty(bool, notify=playPauseChanged)
    def is_play(self):
        return self._is_play

    @pyqtProperty(bool, notify=dataLoadedChanged)
    def data_is_loaded(self):
        return self._data_is_loaded

    @pyqtSlot()
    def play_pause(self):

        # Before enabling data, we need to check if the meta data is 
        # valid, if not, then do nothing
        if not self._data_is_loaded:
            return None

        # Change the state
        self._is_play = not self._is_play
       
        # If now we are playing,
        if self.is_play:

            # Continue the update timer
            # self.current_time_update.resume()

            # First, check if the session has been run complete, if so
            # restart it
            if self.session_complete:

                # print("Restarted detected!")
                self.restart()

        # else, we are stopping!
        else:
            ...

            # # Pause the update timer
            # self.current_time_update.pause()

        # Update the button icon's and other changes based on is_play property
        self.playPauseChanged.emit()

    def message_set_loading_window_loader(self, loading_window):
        
        # Set the time window to starting loading data
        loading_window_message = {
            'header': 'UPDATE',
            'body': {
                'type': 'LOADING_WINDOW',
                'content': {
                    'loading_window': loading_window
                }
            }
        }
        self.message_to_loading_queue.put(loading_window_message)
    
    def message_pause_loader(self):

        # Sending the message to loader to pause!
        message = {
            'header': 'META',
            'body': {
                'type': 'PAUSE',
                'content': {},
            }
        }
        self.message_to_loading_queue.put(message)

    def message_pause_sorter(self):

        # Sending the message to sorter to pause!
        message = {
            'header': 'META',
            'body': {
                'type': 'PAUSE',
                'content': {},
            }
        }
        self.message_to_sorting_queue.put(message)
    
    def message_resume_loader(self):

        # Sending the message to loader to resume!
        message = {
            'header': 'META',
            'body': {
                'type': 'RESUME',
                'content': {},
            }
        }
        self.message_to_loading_queue.put(message)
    
    def message_resume_sorter(self):

        # Sending the message to sorter to resume!
        message = {
            'header': 'META',
            'body': {
                'type': 'RESUME',
                'content': {},
            }
        }
        self.message_to_sorting_queue.put(message)

    def message_end_loading_and_sorting(self):
        
        # Informing all process to end
        message = {
            'header': 'META',
            'body': {
                'type': 'END',
                'content': {},
            }
        }
        for message_to_queue in [self.message_to_sorting_queue, self.message_to_loading_queue]:
            message_to_queue.put(message)

    def respond_loader_message_timetrack(self, timetrack, windows):
        self.timetrack = timetrack
        self.num_of_windows = len(windows)

    def respond_loader_message_counter(self, uuid, loading_window, data_memory_usage):
        self.latest_window_loaded = loading_window
        self.loading_queue_memory_chunks[uuid] = data_memory_usage
        new_state = loading_window / len(self.windows)
        self.loading_bar.state = new_state

    def respond_loader_message_end(self):
        self.loader_finished = True

    def respond_sorter_message_counter(self, uuid, loaded_time, data_memory_usage):
        new_state = loaded_time / self.end_time
        self.sorting_bar.state = new_state
        self.sorting_queue_memory_chunks[uuid] = data_memory_usage

    def respond_sorter_message_memory(self, uuid):
        while uuid not in self.loading_queue_memory_chunks:
            time.sleep(0.01)
        del self.loading_queue_memory_chunks[uuid]

    def respond_sorter_message_end(self):
        self.sorter_finished = True
        self.sorting_bar.state = 1

    @threaded
    def check_messages(self):

        # Set the flag to check if new message
        loading_message = None
        loading_message_new = False
        sorting_message = None
        sorting_message_new = False
        
        # Constantly check for messages
        while not self.thread_exit.is_set():
            
            # Checking the loading message queue
            try:
                loading_message = self.message_from_loading_queue.get(timeout=0.01)
                loading_message_new = True
            except queue.Empty:
                loading_message_new = False

            # Ckecking the sorting message queue
            try:
                sorting_message = self.message_from_sorting_queue.get(timeout=0.01)
                sorting_message_new = True
            except queue.Empty:
                sorting_message_new = False

            # Processing new loading messages
            if loading_message_new:

                # Printing if verbose
                if self.verbose:
                    print("NEW LOADING MESSAGE: ", loading_message)

                # Obtain the function and execute it, by passing the 
                # message
                func = self.respond_message_protocol['LOADER'][loading_message['header']][loading_message['body']['type']]

                # Execute the function and pass the message
                func(**loading_message['body']['content'])

            # Processing new sorting messages
            if sorting_message_new:
                
                # Printing if verbose
                if self.verbose:
                    print("NEW SORTING MESSAGE: ", sorting_message)

                # Obtain the function and execute it, by passing the 
                # message
                func = self.respond_message_protocol['SORTER'][sorting_message['header']][sorting_message['body']['type']]

                # Execute the function and pass the message
                func(**sorting_message['body']['content'])
            
            # Check if the memory limit is passed
            self.sorter_memory_used = sum(list(self.sorting_queue_memory_chunks.values()))
            self.loader_memory_used = sum(list(self.loading_queue_memory_chunks.values()))
            self.total_memory_used = self.sorter_memory_used + self.loader_memory_used

            print(f"LOADER [{self.loading_queue.qsize()}]: {self.loader_memory_used/self.total_available_memory}, SORTER [{self.sorting_queue.qsize()}]: {self.sorter_memory_used/self.total_available_memory}, RATIO: {self.total_memory_used / self.total_available_memory}")

            # If the system is supposed to continue operating, keep 
            # regulating the memory.
            if self.stop_everything is False:

                # Check if we need to pause the sorter
                if self.loader_memory_used > self.loader_memory_ratio *self.total_available_memory and not self.loader_paused:
                    # Pause the sorting and wait until memory is cleared!
                    self.message_pause_loader()
                    self.loader_paused = True
                elif self.loader_memory_used < self.loader_memory_ratio *self.total_available_memory and self.loader_paused:
                    self.message_resume_loader()
                    self.loader_paused = False

                # Check if we need to pause the sorter
                if self.sorter_memory_used > (1-self.loader_memory_ratio)*self.total_available_memory and not self.sorter_paused:
                    # Pause the sorting and wait until memory is cleared!
                    self.message_pause_sorter()
                    self.sorter_paused = True
                elif self.sorter_memory_used < (1-self.loader_memory_ratio)*self.total_available_memory and self.sorter_paused:
                    self.message_resume_sorter()
                    self.sorter_paused = False

    @pyqtSlot()
    def restart(self):

        print("Restarting!")

        # Send message to loading and sorting process to halt!
        self.stop_everything = True
        self.message_pause_loader()
        self.message_pause_sorter()
        self.sorter_paused = True
        self.loader_paused = True

        # Waiting until the processed halted
        time.sleep(0.05)

        # Clear the queues
        while self.loading_queue.qsize():
            clear_queue(self.loading_queue)
        while self.sorting_queue.qsize():
            clear_queue(self.sorting_queue)

        # Delete all the memory
        self.loading_queue_memory_chunks = {}
        self.sorting_queue_memory_chunks = {}
        
        # Set the time to the start_time
        self.current_time = self.start_time
        self._sliding_bar.state = self.current_time / (self.end_time) 

        # Set the window of the loader
        self.message_set_loading_window_loader(0)

        # Waiting until the loading window message is processed
        time.sleep(0.05)

        # Continue the processes
        self.message_resume_loader()
        self.message_resume_sorter()
        self.sorter_paused = False
        self.loader_paused = False
        self.stop_everything = False

        # Typically after rewind, the video is played
        self._is_play = True
        self.playPauseChanged.emit()
    
    def get_meta(self):

        # Obtain all the meta files
        root_meta = self.logdir / 'meta.json' 

        # If no meta, then provide error message through a page.
        if not root_meta.exists(): # Change the page to Home page
            if self._page != "homePage":
                self._page = "homePage"
                self.pageChanged.emit()
            return None # Exit early

        else: # Change the page to Dashboard page
            self._page = "dashboardPage"
            self.pageChanged.emit()

        # Else, get the initial and all other meta files
        with open(root_meta, 'r') as f:
            meta_data = json.load(f)
            meta_data['is_subsession'] = False

        # Check if there is any subsessions and get their meta
        total_meta = {'root': meta_data}
        for sub_id in meta_data['subsessions']:
            with open(self.logdir / sub_id / 'meta.json', 'r') as f:
                total_meta[sub_id] = json.load(f)
                total_meta[sub_id]['is_subsession'] = True

        return total_meta

    def load_data_streams(self, unique_users:List, users_meta:Dict) -> Dict[str, Sequence[DataStream]]:

        # Loading data streams
        users_data_streams = collections.defaultdict(list)
        for user_name, user_meta in tqdm.tqdm(zip(unique_users, users_meta), disable=not self.verbose):
            for index, row in user_meta.iterrows():

                # Extract useful meta
                entry_name = row['entry_name']
                dtype = row['dtype']

                # Construct the directory the file/directory is found
                if row['is_subsession']:
                    file_dir = self.logdir / row['user']
                else:
                    file_dir = self.logdir
                
                # Load the data
                if dtype == 'video':
                    ds = VideoDataStream(
                        name=entry_name,
                        start_time=row['start_time'],
                        video_path=file_dir/f"{entry_name}.avi"
                    )
                elif dtype == 'image':

                    # Load the meta CSV
                    df = pd.read_csv(file_dir/entry_name/'timestamps.csv')

                    # Load all the images into a data frame
                    img_filepaths = []
                    for index, row in df.iterrows():
                        img_fp = file_dir / entry_name / f"{row['idx']}.jpg"
                        img_filepaths.append(img_fp)

                    df['img_filepaths'] = img_filepaths
                    
                    # Create ds
                    ds = TabularDataStream(
                        name=entry_name,
                        data=df,
                        time_column='_time_'
                    )
                elif dtype == 'tabular':
                    raise NotImplementedError("Tabular visualization is still not implemented.")
                else:
                    raise RuntimeError(f"{dtype} is not a valid option.")

                # Store the data in Dict
                users_data_streams[user_name].append(ds)

        return users_data_streams

    def create_entries_df(self, new_logdir_records:Dict) -> pd.DataFrame:

        # Construct pd.DataFrame for the data
        # For each session data, store entries by modality
        entries = collections.defaultdict(list)
        for session_name, session_data in new_logdir_records.items():
            for entry_name, entry_data in session_data['records'].items():

                # For now, skip any tabular data since we don't have a way to visualize
                if entry_data['dtype'] == 'tabular':
                    continue

                entries['user'].append(session_name)
                entries['entry_name'].append(entry_name)
                entries['dtype'].append(entry_data['dtype'])
                entries['start_time'].append(pd.to_timedelta(entry_data['start_time']))
                entries['end_time'].append(pd.to_timedelta(entry_data['end_time']))
                entries['is_subsession'].append(session_data['is_subsession'])

                if entries['end_time'][-1] > self.end_time:
                    self.end_time = entries['end_time'][-1]

        # Construct the dataframe
        entries = pd.DataFrame(dict(entries))

        return entries

    def meta_update(self):
        
        # In the update function, we need to check the data stored in 
        # the logdir.
        new_logdir_records = self.get_meta()

        # If the new is different and not None, we need to update!
        if new_logdir_records: 

            # If this is the first time loading data
            if type(self.logdir_records) == type(None):

                # We need to determine the earliest start_time and the latest
                # end_time
                self.start_time = pd.Timedelta(seconds=0)
                self.end_time = pd.Timedelta(seconds=0)

                # Construct the entries in a pd.DataFrame
                self.entries = self.create_entries_df(new_logdir_records)

                # Add the data to the dashboard
                self._dashboard_model.update_data(self.entries)
                self._timetrack_model.update_data(self.entries, self.start_time, self.end_time)

                # Loading the data for the Collector
                unique_users = self.entries['user'].unique()
                users_meta = [self.entries.loc[self.entries['user'] == x] for x in unique_users]

                # Reset index and drop columns
                for i in range(len(users_meta)):
                    users_meta[i].reset_index(inplace=True)
                    users_meta[i] = users_meta[i].drop(columns=['index'])

                # Load the data streams to later pass to the Loader
                self.users_data_streams = self.load_data_streams(unique_users, users_meta)

                # Setting up the data pipeline
                self.setup()
                
                # Update the flag tracking if data is loaded
                self._data_is_loaded = True
                self.dataLoadedChanged.emit()

            # If this is now updating already loaded data
            elif new_logdir_records != self.logdir_records:
                # TODO: add constant updating
                ...

        # The meta data is invalid or not present
        else:
            if self._data_is_loaded:
                self._data_is_loaded = False
                self.dataLoadedChanged.emit()
            
        # Then overwrite the records
        self.logdir_records = new_logdir_records
   
    def init_loader(self):
        
        # Then, create the data queues for loading and logging
        self.loading_queue = mp.Queue(maxsize=self.max_loading_queue_size)

        # Then create the message queues for the loading subprocess
        self.message_to_loading_queue = mp.Queue(maxsize=self.max_message_queue_size)
        self.message_from_loading_queue = mp.Queue(maxsize=self.max_message_queue_size)

        # Create variables to track the loader's data
        self.num_of_windows = 0
        self.latest_window_loaded = 0
        self.loader_finished = False
        self.loader_paused = False

        # Create the Loader with the specific parameters
        self.loader = Loader(
            loading_queue=self.loading_queue,
            message_to_queue=self.message_to_loading_queue,
            message_from_queue=self.message_from_loading_queue,
            users_data_streams=self.users_data_streams,
            time_window=self.time_window,
            verbose=self.verbose
        )
        
        # Storing the loading queues
        self.queues.update({
            'loading': self.loading_queue,
            'm_to_loading': self.message_to_loading_queue, 
            'm_from_loading': self.message_from_loading_queue,
        })

    def init_sorter(self):
        # Create the queue for sorted data 
        self.sorting_queue = mp.Queue()
        
        # Then create the message queues for the sorting subprocess
        self.message_to_sorting_queue = mp.Queue(maxsize=self.max_message_queue_size)
        self.message_from_sorting_queue = mp.Queue(maxsize=self.max_message_queue_size)

        # Variables to track the sorter
        self.sorter_paused = False
        self.sorter_finished = False

        # Storing the sorting queues
        self.queues.update({
            'sorting': self.sorting_queue,
            'm_to_sorting': self.message_to_sorting_queue, 
            'm_from_sorting': self.message_from_sorting_queue,
        })
        
        # Creating a subprocess that takes the windowed data and loads
        # it to a queue sorted in a time-chronological fashion.
        self.sorter = Sorter(
            loading_queue=self.loading_queue,
            sorting_queue=self.sorting_queue,
            message_to_queue=self.message_to_sorting_queue,
            message_from_queue=self.message_from_sorting_queue,
            entries=self.entries,
            verbose=self.verbose
        )
    
    def setup(self):
        
        # Changing the time_window_size based on the number of entries
        div_factor = min(len(self.entries), 10)
        self.time_window = pd.Timedelta(seconds=(self.time_window.value/1e9)/div_factor)
                
        # Get the necessary information to create the Collector 
        self.windows = get_windows(self.start_time, self.end_time, self.time_window)
        self.update_content_times = collections.deque(maxlen=100)
     
        # Starting the Manager's messaging thread and the content update thread
        self.check_messages_thread = self.check_messages()
        self.update_content_thread = self.update_content()

        # Create container for all queues
        self.queues = {}

        # Starting the loader and sorter
        self.init_loader()
        self.init_sorter()

        # Start the threads
        self.check_messages_thread.start()
        self.update_content_thread.start()

        # Start the processes
        self.loader.start()
        self.sorter.start()

    @threaded
    def update_content(self):

        # Keep repeating until exiting the app
        while not self.thread_exit.is_set():

            # Only processing if we have the global timetrack
            if type(self.timetrack) == type(None):
                time.sleep(1)
                continue

            # Also, not processing if not playing or the session is complete
            if not self._is_play or self.session_complete:
                time.sleep(0.05)
                continue
 
            # Get the next entry information!
            try:
                data_chunk = self.sorting_queue.get(timeout=0.1)
            except queue.Empty:
                print('EMPTY')
                # Check if all the data has been loaded, if so that means
                # that all the data has been played
                if self.sorting_bar.state == 1:
                    print("Session end detected!")
                    self.session_complete = True
                    self._is_play = False
                    self.playPauseChanged.emit()
                
                # Regardless, continue
                continue
            
            # Get the time before updating
            tic = time.time()

            # Update the memory used by the sorting queue
            if data_chunk['uuid']:
                while data_chunk['uuid'] not in self.sorting_queue_memory_chunks:
                    time.sleep(0.01)
                del self.sorting_queue_memory_chunks[data_chunk['uuid']]
            
            # Compute the average time it takes to update content, and its ratio 
            # to the expect time, clipping at 1
            average_update_delta = sum(self.update_content_times)/max(1, len(self.update_content_times))

            # Calculate the delta between the current time and the entry's time
            time_delta = (data_chunk['entry_time'] - self.current_time).value / 1e9
            time_delta = max(0,time_delta-average_update_delta) # Accounting for updating
            time.sleep(time_delta)

            # Updating sliding bar
            self.current_time = data_chunk['entry_time']
            self._sliding_bar.state = self.current_time / (self.end_time) 

            # Update the content
            self._dashboard_model.update_content(
                data_chunk['index'],
                data_chunk['user'],
                data_chunk['entry_name'],
                data_chunk['content']
            )

            # Computing the time difference of uploading content
            tac = time.time()
            delta = tac - tic

            # Finally update the sliding bar
            self.update_content_times.append(delta)
    
    def exit(self):

        print("Closing")

        # Only execute the thread and process ending if data is loaded
        if self._data_is_loaded:

            # Inform all the threads to end
            self.thread_exit.set()
            # print("Stopping threads!")

            self.check_messages_thread.join()
            # print("Checking message thread join")
            
            self.update_content_thread.join()
            # print("Content update thread join")
            # self.current_time_update.stop()
            # print("Content timer stopped")

            self.message_end_loading_and_sorting()

            # Clearing Queues to permit the processes to shutdown
            # print("Clearing queues")
            for q_name, queue in self.queues.items():
                # print(f"Clearing {q_name} queue")
                clear_queue(queue)

            # Then wait for threads and process
            # print("Clearing loading queue again")
            while self.loading_queue.qsize():
                clear_queue(self.loading_queue)
                time.sleep(0.2)

            self.loader.join()
            # print("Loading process join")

            time.sleep(0.3)
            
            # Clearing Queues to permit the processes to shutdown
            # print("Clearing all queues again")
            for q_name, queue in self.queues.items():
                # print(f"clearing {q_name}.")
                clear_queue(queue)

            # print("Clearing sorting queue again")
            while self.sorting_queue.qsize():
                # print(self.sorting_queue.qsize())
                clear_queue(self.sorting_queue)
                time.sleep(0.2)

            self.sorter.join()
            # print("Sorting process join")

        # print("Finished closing")
