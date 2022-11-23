# Built-in Imports
import os
import pathlib
import logging
import time
import uuid

# Third-party
import numpy as np
import pytest
import chimerapy as cp

logger = logging.getLogger("chimerapy")

# Constants
CWD = pathlib.Path(os.path.abspath(__file__)).parent.parent
TEST_DATA_DIR = CWD / "data"


class ImageNode(cp.Node):
    def step(self):
        time.sleep(1 / 30)
        rand_frame = np.random.rand(200, 300, 3) * 255
        self.save_image(name="test", data=rand_frame)


@pytest.fixture
def image_node():

    # Create a node
    img_n = ImageNode(name="img_n")
    img_n.config("", 9000, TEST_DATA_DIR, [], [], follow=None, networking=False)
    img_n._prep()

    return img_n


def test_image_record():

    # Check that the image was created
    expected_image_path = TEST_DATA_DIR / "test" / "0.png"
    try:
        os.rmdir(expected_image_path.parent)
    except OSError:
        ...

    # Create the record
    img_r = cp.records.ImageRecord(dir=TEST_DATA_DIR, name="test")

    # Write to image file
    for i in range(5):
        data = np.random.rand(200, 300, 3) * 255
        image_chunk = {
            "uuid": uuid.uuid4(),
            "name": "test",
            "data": data,
            "dtype": "image",
        }
        img_r.write(image_chunk)

    # Check that the image was created
    assert expected_image_path.exists()


def test_save_handler_image(save_handler_and_queue):

    # Decoupling
    save_handler, save_queue = save_handler_and_queue

    # Check that the image was created
    expected_image_path = TEST_DATA_DIR / "test" / "0.png"
    try:
        os.rmdir(expected_image_path.parent)
    except OSError:
        ...

    # Write to image file
    for i in range(5):
        data = np.random.rand(200, 300, 3) * 255
        image_chunk = {
            "uuid": uuid.uuid4(),
            "name": "test",
            "data": data,
            "dtype": "image",
        }

        save_queue.put(image_chunk)

    # Shutdown save handler
    save_handler.shutdown()
    save_handler.join()

    # Check that the image was created
    assert expected_image_path.exists()


def test_node_save_image_single_step(image_node):

    # Check that the image was created
    expected_image_path = image_node.logdir / "test" / "0.png"
    try:
        os.rmdir(expected_image_path.parent)
    except OSError:
        ...

    for i in range(5):
        image_node.step()

    # Stop the node the ensure image completion
    image_node.shutdown()
    image_node._teardown()

    # Check that the image was created
    assert expected_image_path.exists()


def test_node_save_image_stream(image_node):

    # Check that the image was created
    expected_image_path = image_node.logdir / "test" / "0.png"
    try:
        os.rmdir(expected_image_path.parent)
    except OSError:
        ...

    # Stream
    image_node.start()

    # Wait to generate files
    time.sleep(10)

    image_node.shutdown()
    image_node._teardown()
    image_node.join()

    # Check that the image was created
    assert expected_image_path.exists()
