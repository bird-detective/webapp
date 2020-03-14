"""
watch the stream, send video frames to worker
"""
from typing import NoReturn

import cv2
import imagehash
import logging

from datetime import datetime
from django.conf import settings
from queue import Queue
from PIL import Image
from threading import Thread

from .tasks import filter_frame

logging.basicConfig(level=logging.INFO)
__logger__ = logging.getLogger(__name__)


def main() -> None:
    def motion_detector() -> NoReturn:
        def hashify(f):
            cv2_image = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            pillow_image = Image.fromarray(cv2_image)
            phash = imagehash.phash(pillow_image)

            return phash

        def compare_frames(a, b) -> bool:
            threshold = settings.MOTION_DETECTOR_PHASH_THRESHOLD
            difference = b - a
            return difference > threshold

        previous_frame_hashes = []

        motion_detected = False
        motion_detected_at = datetime.utcnow()

        while True:
            # TODO should be state machine
            frame, timestamp = queue.get()

            if motion_detected:
                __logger__.info("MOTION: Sent frame")
                filter_frame.delay(frame, timestamp)

                now = datetime.utcnow()

                if (now - motion_detected_at).total_seconds() > 3.0:
                    # Stop sending frames
                    __logger__.info("MOTION: No longer sending frames")
                    motion_detected = False

                continue

            current = hashify(frame)

            # compare latest frame against previous frames
            if any(
                compare_frames(previous, current) for previous in previous_frame_hashes
            ):
                __logger__.info(
                    "MOTION: Detected motion, sending all frames for 3 seconds"
                )

                filter_frame.delay(frame, timestamp)

                motion_detected = True
                motion_detected_at = datetime.utcnow()
            else:
                previous_frame_hashes.insert(0, current)
                previous_frame_hashes = previous_frame_hashes[:5]

    # TODO VideoCapture source should be set by environment variable
    cap = cv2.VideoCapture(settings.VIDEO_SOURCE)

    queue = Queue()

    thread = Thread(target=motion_detector)
    thread.start()

    if not cap.isOpened():
        raise RuntimeError("Failed to open video!")

    counter = 0
    start = datetime.utcnow()

    while cap.isOpened():

        ret, frame = cap.read()

        if not ret:
            raise RuntimeError()

        counter += 1

        __logger__.info(
            f"STREAM: Running at {counter / (datetime.utcnow() - start).total_seconds()} fps"
        )

        queue.put((frame, datetime.utcnow()))

        cv2.imshow("frame", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
