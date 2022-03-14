"""."""
__package__ = "pymmdt"

# Built-in Imports
from typing import Sequence, Dict, Any, Union, List, Optional
import curses
import time
import threading
import multiprocessing as mp
import queue
import gc
import pathlib
import pprint

# Third-Party Imports
import psutil
import pandas as pd
import tqdm

# Internal Imports
from .loader import Loader
from .logger import Logger
from .core.pipe import Pipe
from .core.data_stream import DataStream
from .core.session import Session
from .core.tools import get_memory_data_size, threaded

class SingleRunner:
    
    def __init__(
            self,
            name:str,
            pipe:Pipe,
            data_streams:Sequence[DataStream],
            run_solo:bool=False,
            time_window:pd.Timedelta=pd.Timedelta(seconds=5),
            logdir:Optional[Union[str, pathlib.Path]]=None,
            start_time:Optional[pd.Timedelta]=None,
            end_time:Optional[pd.Timedelta]=None,
            max_loading_queue_size:int=100,
            max_logging_queue_size:int=1000,
            max_message_queue_size:int=100,
            memory_limit:float=0.8,
            verbose=True,
        ):

        # Convert the logdir to pathlib
        if isinstance(logdir, str):
            self.logdir = pathlib.Path(logdir)
        else:
            self.logdir = logdir

        # Store the information
        self.name = name
        self.pipe = pipe
        self.data_streams = data_streams
        self.run_solo = run_solo
        self.max_loading_queue_size = max_loading_queue_size
        self.max_logging_queue_size = max_logging_queue_size
        self.max_message_queue_size = max_message_queue_size
        self.verbose = verbose

        # Keep track of the number of processed data chunks
        self.num_processed_data_chunks = 0
        self.total_available_memory = memory_limit * psutil.virtual_memory().available
        self.loading_queue_memory_chunks = {}
        self.logging_queue_memory_chunks = {}
        self.total_memory_used = 0

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
            'LOGGER':{
                'UPDATE': {
                    'COUNTER': self.respond_logger_message_counter
                },
                'META': {
                    'END': self.respond_logger_message_end
                }
            }
        }

        # If the runner is running by itself, it should be able to have 
        # its own collector.
        if self.run_solo:

            # If running solo, then a logdir should be provided
            assert isinstance(self.logdir, pathlib.Path), f"param ``logdir`` \
                is required when ``run_solo`` is set to ``True``."

            # Keeping track of queues and placing the data streams inside 
            # a dictionary
            self.queues = {}
            self.users_data_streams = {f"{self.name}": self.data_streams}
            
            # Setup the loader
            self.init_loader(
                time_window,
                self.max_loading_queue_size, 
                start_time,
                end_time
            )

            # Setup the logger
            self.init_logger(
                self.max_logging_queue_size,
            )

            # Create session for runner
            self.session = Session(
                name='root',
                logging_queue=self.logging_queue
            )
            self.session.set_runner(self)
            self.pipe.set_session(self.session)

    def init_loader(
            self, 
            time_window:pd.Timedelta,
            max_loading_queue_size:int,
            start_time:Optional[pd.Timedelta],
            end_time:Optional[pd.Timedelta]
        ) -> None:

        # Then, create the data queues for loading and logging
        self.loading_queue = mp.Queue(maxsize=max_loading_queue_size)

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
            time_window=time_window,
            start_time=start_time,
            end_time=end_time,
            verbose=self.verbose
        )
        
        # Storing the loading queues
        self.queues.update({
            'loading': self.loading_queue,
            'm_to_loading': self.message_to_loading_queue, 
            'm_from_loading': self.message_from_loading_queue,
        })

    def init_logger(
            self,
            max_logging_queue_size:int,
        ) -> None:

        # Create the queue for the logging data
        self.logging_queue = mp.Queue(maxsize=max_logging_queue_size)
       
        # Create the queues for the logger messaging 
        self.message_to_logging_queue = mp.Queue(maxsize=self.max_message_queue_size)
        self.message_from_logging_queue = mp.Queue(maxsize=self.max_message_queue_size)

        # Creating variables to track the logger's data
        self.num_of_logged_data = 0
        self.logger_finished = False

        # Create the logger
        self.logger = Logger(
            logdir=self.logdir,
            experiment_name=self.name,
            logging_queue=self.logging_queue,
            message_to_queue=self.message_to_logging_queue,
            message_from_queue=self.message_from_logging_queue,
            verbose=self.verbose
        )

        # Storing the logging queues
        self.queues.update({
            'logging': self.logging_queue,
            'm_to_logging': self.message_to_logging_queue,
            'f_to_logging': self.message_from_logging_queue
        })

    def message_pause_loader(self):

        # Sending the message to loader to pause!
        pause_message = {
            'header': 'META',
            'body': {
                'type': 'PAUSE',
                'content': {},
            }
        }
        self.message_to_loading_queue.put(pause_message)
    
    def message_resume_loader(self):

        # Sending the message to loader to pause!
        pause_message = {
            'header': 'META',
            'body': {
                'type': 'RESUME',
                'content': {},
            }
        }
        self.message_to_loading_queue.put(pause_message)

    def message_end_loading_and_logging(self):

        # Sending message to loader and logger to stop!
        end_message = {
            'header': 'META',
            'body': {
                'type': 'END',
                'content': {},
            }
        }
        self.message_to_loading_queue.put(end_message)
        self.message_to_logging_queue.put(end_message)

    def respond_loader_message_timetrack(self, timetrack, windows):
        self.timetrack = timetrack
        self.num_of_windows = len(windows)

    def respond_loader_message_counter(self, uuid, loading_window, data_memory_usage):
        self.latest_window_loaded = loading_window
        self.loading_queue_memory_chunks[uuid] = data_memory_usage

    def respond_logger_message_counter(self, num_of_logged_data, uuid):
        self.num_of_logged_data = num_of_logged_data
        while uuid not in self.logging_queue_memory_chunks:
            time.sleep(0.01)
        del self.logging_queue_memory_chunks[uuid]

    def respond_loader_message_end(self):
        self.loader_finished = True

    def respond_logger_message_end(self):
        self.logger_finished = True

    @threaded
    def check_messages(self):

        # Set the flag to check if new message
        loading_message = None
        loading_message_new = False
        logging_message = None
        logging_message_new = False
        
        # Constantly check for messages
        while not self.thread_exit.is_set():
            
            # Prevent blocking, as we need to check if the thread_exist
            # is set.
            while not self.thread_exit.is_set():

                # Checking the loading message queue
                try:
                    loading_message = self.message_from_loading_queue.get(timeout=0.1)
                    loading_message_new = True
                except queue.Empty:
                    loading_message_new = False

                # Ckecking the logging message queue
                try:
                    logging_message = self.message_from_logging_queue.get(timeout=0.1)
                    logging_message_new = True
                except queue.Empty:
                    logging_message_new = False

                # If new message, process it right now
                if loading_message_new or logging_message_new:
                    break

                # else, placing a sleep timer
                time.sleep(0.1)
              
            # Processing new loading messages
            if loading_message_new:

                # Obtain the function and execute it, by passing the 
                # message
                func = self.respond_message_protocol['LOADER'][loading_message['header']][loading_message['body']['type']]

                # Execute the function and pass the message
                func(**loading_message['body']['content'])

            # Processing new sorting messages
            if logging_message_new:

                # Obtain the function and execute it, by passing the 
                # message
                func = self.respond_message_protocol['LOGGER'][logging_message['header']][logging_message['body']['type']]

                # Execute the function and pass the message
                func(**logging_message['body']['content'])

            # Check if the memory limit is passed
            self.total_memory_used = sum(list(self.logging_queue_memory_chunks.values())) + sum(list(self.loading_queue_memory_chunks.values()))
            
            # print(f"TMU: {total_memory_used}, AVAILABLE: {self.total_available_memory}, RATIO: {total_memory_used / self.total_available_memory}")
            if self.total_memory_used > self.total_available_memory and not self.loader_paused:
                # Pause the loading and wait until memory is cleared!
                self.message_pause_loader()
                self.loader_paused = True
            elif self.total_memory_used < self.total_available_memory and self.loader_paused:
                # resume the loading and wait until memory is cleared!
                self.message_resume_loader()
                self.loader_paused = False

    def set_session(self, session: Session) -> None:
        if hasattr(self, 'session'):
            raise RuntimeError(f"Runner <name={self.name}> has already a Session")
        else:
            self.session = session

    def setup(self) -> None:

        # Creating threading Event to indicate stopping processing
        self.thread_exit = threading.Event()
        self.thread_exit.clear()
        
        # Begin the thread receiving messages
        self.message_thread = self.check_messages()
        self.message_thread.start()
        
        # Start the loader and logger
        self.loader.start()
        self.logger.start()

    def start(self) -> None:
        
        # set the session to the pipe
        self.pipe.set_session(self.session)

        # First, execute the ``start`` routine of the pipe
        self.pipe.start()

    def step(self, data_samples: Dict[str, Dict[str, Union[pd.DataFrame, List[pd.DataFrame]]]]) -> Any:

        # Then process the sample
        output = self.pipe.step(data_samples[self.name])

        # Return the pipe's output
        return output
    
    def end(self) -> None:
        
        # Closing components
        self.pipe.end()

    def shutdown(self) -> None:

        # Stop the loader and logger
        self.message_end_loading_and_logging() 

        # Now we have to wait until the logger is done
        while True:

            # Waiting 
            time.sleep(0.1)

            # Checking end condition
            # Break Condition
            # print(self.loader_finished, self.logger_finished)
            if self.loader_finished and \
                self.logger_finished:
                break

        # If the thread ended, we should stop the message thread
        self.thread_exit.set()
        
        # Joining the subprocesses
        self.loader.join()
        self.logger.join()

        # Waiting for the threads to shutdown
        self.message_thread.join()

    def process_data(self):

        # Keep track of the number of processed data chunks
        self.num_processed_data_chunks = 0
        
        # Continue iterating
        while True:

            # Retrieveing sample from the loading queue
            data_chunk = self.loading_queue.get(block=True)
            
            # Check for end condition
            if data_chunk == 'END':
                break

            # Decompose the data chunk
            all_data_samples = data_chunk['data'] 
 
            # Now that the data has been removed from the queue, remove 
            # this from the memory used
            while data_chunk['uuid'] not in self.loading_queue_memory_chunks:
                time.sleep(0.01)
            del self.loading_queue_memory_chunks[data_chunk['uuid']]
            
            # Then propagate the sample throughout the pipe
            self.step(all_data_samples)

            # Increase the counter
            self.num_processed_data_chunks += 1
        
    def tui_main(self, stdscr):
        
        # Continue the TUI until the other threads are complete.
        while True:

            # Create information string
            info_str = f"""\
            Loading:
                Loaded Data: {self.latest_window_loaded}/{self.num_of_windows}
                Loading Queue Size: {self.loading_queue.qsize()}/{self.max_loading_queue_size}
            Processing: 
                Processed Data: {self.num_processed_data_chunks}/{self.num_of_windows}
            Logging:
                Logged Data: {self.num_of_logged_data}
                Logging Queue Size: {self.logging_queue.qsize()}/{self.max_logging_queue_size}
            System Information:
                Memory Usage: {(self.total_memory_used/self.total_available_memory):.2f}
            """

            # Info about data loading
            stdscr.addstr(0,0, info_str)

            # Refresh the screen
            stdscr.refresh()

            # Sleep
            time.sleep(0.1)

            # Break Condition
            if self.loader_finished and \
                self.num_processed_data_chunks == self.num_of_windows and \
                self.logger_finished:
                break
    
    def run(self, verbose:bool=False) -> None:
        """Run the data pipeline.

        Args:
            verbose (bool): If to include logging and loading bar to
            help visualize the wait time until completion.

        """
        # Assertions
        assert isinstance(self.session, Session)

        # Performing setup for the subprocesses and threads
        self.setup()
 
        # Start the Runner
        self.start()
 
        # If verbose, create a simple TUI showing the current state of 
        # the whole process.
        if verbose:
            tui_thread = threading.Thread(target=curses.wrapper, args=(self.tui_main,))
            tui_thread.start()

        # Execute the processing in the main thread
        self.process_data()
        
        # End 
        self.end()

        # Then fully shutting down the subprocesses and threads
        self.shutdown()

class GroupRunner(SingleRunner):
    """Multimodal Data Processing Group Director.

    """

    def __init__(
            self, 
            logdir:Union[str, pathlib.Path],
            name:str,
            pipe:Pipe,
            runners:Sequence[SingleRunner],
            time_window:pd.Timedelta,
            data_streams:Sequence[DataStream]=[],
            start_time:pd.Timedelta=None,
            end_time:pd.Timedelta=None,
            max_loading_queue_size:int=100,
            max_logging_queue_size:int=1000,
            max_message_queue_size:int=100,
            memory_limit:float=0.8,
            verbose=True,
        ) -> None:
        """Construct the analyzer. 

        Args:
            data_streams (Sequence[DataStream]): A list of data streams to process forward.
            pipe (Pipe): The pipeline to send forward the data samples from the data streams toward.

        """

        # Convert the logdir to pathlib
        if isinstance(logdir, str):
            self.logdir = pathlib.Path(logdir)
        else:
            self.logdir = logdir

        # Save hyperparameters
        self.name = name
        self.pipe = pipe
        self.data_streams = data_streams
        self.runners = runners
        self.max_loading_queue_size = max_loading_queue_size
        self.max_logging_queue_size = max_logging_queue_size
        self.max_message_queue_size = max_message_queue_size
        self.verbose = verbose
        
        # Keep track of the number of processed data chunks
        self.num_processed_data_chunks = 0
        self.total_available_memory = memory_limit * psutil.virtual_memory().available
        self.loading_queue_memory_chunks = {}
        self.logging_queue_memory_chunks = {}
        self.total_memory_used = 0

        # Extract all the data streams from each runner and the entire group
        if data_streams:
            self.users_data_streams = {self.name: data_streams}
        else:
            self.users_data_streams = {}

        for runner in self.runners:
            self.users_data_streams[runner.name] = runner.data_streams 
        
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
            'LOGGER':{
                'UPDATE': {
                    'COUNTER': self.respond_logger_message_counter
                },
                'META': {
                    'END': self.respond_logger_message_end
                }
            }
        }
            
        # Keeping track of queues and placing the data streams inside 
        # a dictionary
        self.queues = {}
        
        # Setup the loader
        self.init_loader(
            time_window,
            max_loading_queue_size, 
            start_time,
            end_time
        )

        # Setup the logger
        self.init_logger(
            max_logging_queue_size,
        )

        # Creating sessions for the runners
        self.session = Session(
            name='root',
            logging_queue=self.logging_queue
        )
        
        # Providing each runner with a subsession
        for runner in self.runners:
            runner_session = Session(
                name=runner.name,
                logging_queue=self.logging_queue
            )

            # Connect the session to the group runner to track memory usage
            runner_session.set_runner(self)

            # Connect session to runner to make logging tagged by the user
            runner.set_session(runner_session)

            # Connect the session to the pipe since that's how the session
            # is interfaced.
            runner.pipe.set_session(runner_session)
        
    def start(self) -> None:
        
        # Execute the runners' ``start`` routine
        for runner in self.runners:
            runner.start()

        # Execute its own start
        super().start()

    def step(self, all_data_samples: Dict[str, Dict[str, Union[pd.DataFrame, List[pd.DataFrame]]]]) -> None:

        # Get samples for all the runners and propagate them
        for runner in self.runners:
            # Get the output of the each runner
            output = runner.step({runner.name: all_data_samples[runner.name]})
            all_data_samples[runner.name]['_output_'] = output

        # Then process the sample in the group pipeline
        self.pipe.step(all_data_samples)

    def end(self) -> None:

        # Execute the runners' ``end`` routine
        for runner in self.runners:
            runner.end()

        # Execute its own start
        super().end()
