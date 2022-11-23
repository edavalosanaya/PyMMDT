# Built-in Imports
import os
import pathlib
import logging
import uuid
import time

# Third-party
import numpy as np
import pytest
import pyaudio
import chimerapy as cp

logger = logging.getLogger("chimerapy")

# Constants
CWD = pathlib.Path(os.path.abspath(__file__)).parent.parent
TEST_DATA_DIR = CWD / "data"
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
RECORD_SECONDS = 5


class AudioNode(cp.Node):
    def step(self):

        time.sleep(1 / 20)
        data = np.random.rand(CHUNK) * 2 - 1
        self.save_audio(
            name="test", data=data, channels=CHANNELS, format=FORMAT, rate=RATE
        )


@pytest.fixture
def audio_node():

    # Create a node
    an = AudioNode(name="an")
    an.config("", 9000, TEST_DATA_DIR, [], [], follow=None, networking=False)
    an._prep()

    return an


def test_audio_record():

    # Check that the audio was created
    expected_audio_path = TEST_DATA_DIR / "test.wav"
    try:
        os.remove(expected_audio_path)
    except FileNotFoundError:
        ...

    # Create the record
    ar = cp.records.AudioRecord(dir=TEST_DATA_DIR, name="test")

    # Write to audio file
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = (np.random.rand(CHUNK) * 2 - 1) * (i * 0.1)
        audio_chunk = {
            "uuid": uuid.uuid4(),
            "name": "test",
            "data": data,
            "dtype": "audio",
            "channels": CHANNELS,
            "format": FORMAT,
            "rate": RATE,
        }
        ar.write(audio_chunk)

    assert expected_audio_path.exists()


def test_save_handler_audio(save_handler_and_queue):

    # Check that the audio was created
    expected_audio_path = TEST_DATA_DIR / "test.wav"
    try:
        os.remove(expected_audio_path)
    except FileNotFoundError:
        ...

    # Decoupling
    save_handler, save_queue = save_handler_and_queue

    # Write to audio file
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = (np.random.rand(CHUNK) * 2 - 1) * (i * 0.1)
        audio_chunk = {
            "uuid": uuid.uuid4(),
            "name": "test",
            "data": data,
            "dtype": "audio",
            "channels": CHANNELS,
            "format": FORMAT,
            "rate": RATE,
        }
        save_queue.put(audio_chunk)

    # Shutdown save handler
    save_handler.shutdown()
    save_handler.join()

    # Check that the audio was created
    expected_audio_path = save_handler.logdir / "test.wav"
    assert expected_audio_path.exists()


def test_node_save_audio_single_step(audio_node):

    # Check that the audio was created
    expected_audio_path = audio_node.logdir / "test.wav"
    try:
        os.remove(expected_audio_path)
    except FileNotFoundError:
        ...

    # Write to audio file
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        audio_node.step()

    # Stop the node the ensure audio completion
    audio_node.shutdown()
    audio_node._teardown()
    time.sleep(1)

    # Check that the audio was created
    assert expected_audio_path.exists()


def test_node_save_audio_stream(audio_node):

    # Check that the audio was created
    expected_audio_path = audio_node.logdir / "test.wav"
    try:
        os.remove(expected_audio_path)
    except FileNotFoundError:
        ...

    # Stream
    audio_node.start()

    # Wait to generate files
    time.sleep(10)

    audio_node.shutdown()
    audio_node._teardown()
    audio_node.join()

    # Check that the audio was created
    assert expected_audio_path.exists()