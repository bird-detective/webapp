# Necessary because tensorflow spits out a ton of junk warnings
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from typing import List, Tuple, Any

import base64
import cvlib
import pickle

from celery import shared_task
from datetime import datetime, timedelta
from django.conf import settings
from django.core.files.base import ContentFile
from io import BytesIO
from logging import getLogger
from operator import itemgetter
from redis import Redis
from PIL import Image

from colony.models import Visit

__logger__ = getLogger(__name__)


@shared_task
def filter_frame(frame, timestamp: datetime) -> None:
    bboxs, labels, confs = cvlib.detect_common_objects(
        frame, confidence=0.25, model="yolov3-tiny"
    )

    __logger__.info("Analyzed frame: %s %s %s", bboxs, labels, confs)

    for bbox, label, conf in zip(bboxs, labels, confs):
        if label == settings.TARGET_OBJECT:
            __logger__.info(f"Found target object ({settings.TARGET_OBJECT})!")

            persist_to_site.delay(frame, conf, timestamp)


@shared_task
def persist_to_site(frame, conf: float, timestamp: datetime) -> None:
    visit: Visit = Visit.objects.create(confidence=conf, created=timestamp)

    with BytesIO() as buff:
        pil_img = Image.fromarray(frame)
        pil_img.save(buff, format="PNG")

        visit.image.save(f"{visit.id}.png", ContentFile(buff.getvalue()))


@shared_task
def identify_species(frame, timestamp, bbox, label, conf) -> None:
    """
    TODO need ML to identify bird species
    """


@shared_task
def combine_results_add_to_queue(frame, conf: float, timestamp: datetime) -> None:
    """
    append each record to a local database
    """
    redis = Redis()

    data = (timestamp, frame, conf)
    dump = pickle.dumps(data)

    redis.rpush("combine-queue", dump)


@shared_task
def combine_results() -> None:
    """
    summarize results
    """

    def close_enough(first: datetime, later: datetime):
        return (later - first) < timedelta(seconds=1)

    redis = Redis()

    # retrieve and delete the existing records from the database
    pipeline = redis.pipeline()

    pipeline.lrange("combine-queue", 0, -1)
    pipeline.delete("combine-queue")

    pipeline_result = pipeline.execute()

    my_dumps: List[str] = pipeline_result[0]

    # erase the key from the database to

    records: List[Tuple[datetime, float, Any]] = []

    for dump in my_dumps:
        data = pickle.loads(dump)
        records.append(data)

    # sort the records by time (asc)
    records = sorted(records, key=itemgetter(0))

    # filter: throw out all records less than 1 minute old
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    unused_records: List[Tuple[datetime, float, Any]] = [
        record for record in records if record[0] > one_minute_ago
    ]

    records = [record for record in records if record[0] <= one_minute_ago]

    # put the records into buckets
    buckets: List[List] = []

    previous = records.pop(0)
    buckets.append([previous])

    while len(records) != 0:
        current = records.pop(0)

        if close_enough(previous[0], current[0]):
            buckets[-1].append(current)
        else:
            buckets.append([current])

    # check the last bucket to see if the last record runs against the edge of time
    last_bucket = buckets[-1]
    last_record = last_bucket[-1]

    if not close_enough(last_record[1], one_minute_ago):
        # remove this bucket and return to database
        unused_records.extend(buckets.pop(-1))

    # grab the highest scoring record from each bucket
    results: List[Tuple[datetime, float, Any]] = []

    for bucket in buckets:
        best = sorted(bucket, key=itemgetter(1))[0]
        results.append(best)

    # replace unused records in database
    for_queue = [pickle.dumps(unused_record) for unused_record in unused_records]

    redis.lpush("combine-queue", *for_queue)

    # convert numpy array frames to base64 images
    for i in range(len(results)):
        timestamp, conf, frame = results[i]

        pil_img = Image.fromarray(frame)
        buff = BytesIO()
        pil_img.save(buff, format="PNG")
        img = base64.b64encode(buff.getvalue()).decode("utf-8")

        results[i] = (timestamp, conf, img)

    # process the results
    for timestamp, conf, frame in results:

        notify_user.delay(frame, conf, timestamp)
        upload_to_site.delay(frame, conf, timestamp)


@shared_task
def notify_user(frame, timestamp: datetime) -> None:
    pass


@shared_task
def weather_forecast() -> None:
    """
    check for rain in daily forecast, alerting user to remove feeder tray
    """
