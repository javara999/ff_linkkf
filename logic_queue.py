# -*- coding: utf-8 -*-
import os
import queue
import re
import threading
import time
import traceback
from collections import deque
from datetime import datetime

import requests

from framework import F, db, get_logger
from support.expand.ffmpeg import SupportFfmpeg

from .model import ModelLinkkf, ModelSetting
from .subtitle_util import convert_vtt_to_srt, write_file


package_name = __name__.split(".")[0]
logger = get_logger(package_name)


FFMPEG_STATUS_KOR = {
    -1: "대기중",
    0: "준비",
    1: "URL 오류",
    2: "폴더 오류",
    3: "예외",
    4: "오류",
    5: "다운로드중",
    6: "사용자중지",
    7: "완료",
    8: "시간초과",
    9: "PF중지",
    10: "강제중지",
    11: "403 오류",
    12: "중복 다운로드",
    100: "파일 있음",
}

ACTIVE_STATUS = {0, 5}
FINAL_STATUS = {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 100}


class QueueEntity:
    static_index = 1
    entity_list = []

    def __init__(self, info):
        self.entity_id = QueueEntity.static_index
        QueueEntity.static_index += 1

        self.info = info
        self.episodecode = info["code"]
        self.url = None
        self.ffmpeg_status = -1
        self.ffmpeg_status_kor = FFMPEG_STATUS_KOR[-1]
        self.ffmpeg_percent = 0
        self.ffmpeg_arg = None
        self.ffmpeg_callback_id = None
        self.ffmpeg_idx = None
        self.ffmpeg_finalized = False
        self.cancel = False
        self.created_time = datetime.now().strftime("%m-%d %H:%M:%S")
        self.status = -1

        QueueEntity.entity_list.append(self)

    @staticmethod
    def get_entity_by_entity_id(entity_id):
        target = str(entity_id)
        for item in QueueEntity.entity_list:
            if str(item.entity_id) == target:
                return item


class LogicQueue(object):
    download_queue = None
    download_thread = None
    monitor_thread = None
    current_ffmpeg_count = 0

    @staticmethod
    def queue_start():
        try:
            if LogicQueue.download_queue is None:
                LogicQueue.download_queue = queue.Queue()
            if LogicQueue.download_thread is None:
                LogicQueue.download_thread = threading.Thread(
                    target=LogicQueue.download_thread_function,
                    daemon=True,
                )
                LogicQueue.download_thread.start()
            if LogicQueue.monitor_thread is None:
                LogicQueue.monitor_thread = threading.Thread(
                    target=LogicQueue.monitor_thread_function,
                    daemon=True,
                )
                LogicQueue.monitor_thread.start()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def _make_save_path(info):
        save_path = ModelSetting.get("download_path")
        if ModelSetting.get("auto_make_folder") == "True":
            save_path = os.path.join(save_path, info["save_folder"])
            if ModelSetting.get("linkkf_auto_make_season_folder") == "True":
                save_path = os.path.join(save_path, f"Season {int(info['season'])}")
        return save_path

    @staticmethod
    def _make_headers(video_info):
        referer = video_info[1] or f"{ModelSetting.get('linkkf_url').rstrip('/')}/"
        return {
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/104.0.0.0 Safari/537.36"
            ),
            "Referer": referer,
        }

    @staticmethod
    def _ensure_db_entity(info, reset_state=False):
        with F.app.app_context():
            episode = db.session.query(ModelLinkkf).filter_by(episodecode=info["code"]).with_for_update().first()
            if episode is None:
                episode = ModelLinkkf("auto", info=info)
                db.session.add(episode)
            else:
                episode.set_info(info)
            if reset_state:
                episode.completed = False
                episode.user_abort = False
                episode.pf_abort = False
                episode.etc_abort = 0
                episode.ffmpeg_status = -1
                episode.completed_time = None
                episode.end_time = None
                episode.download_time = None
                episode.filesize = None
                episode.filesize_str = None
                episode.download_speed = None
                episode.start_time = datetime.now()
                episode.status = "waiting"
            episode.filename = info.get("filename", episode.filename)
            episode.save_path = LogicQueue._make_save_path(info)
            db.session.commit()
            return episode

    @staticmethod
    def _make_runtime_snapshot(entity):
        data = {}
        if isinstance(entity.ffmpeg_arg, dict):
            data = entity.ffmpeg_arg.get("data") or {}
        data = dict(data)
        data.setdefault("status", entity.ffmpeg_status)
        data.setdefault("filename", entity.info.get("filename"))
        data.setdefault("save_path", LogicQueue._make_save_path(entity.info))
        data.setdefault("percent", entity.ffmpeg_percent)
        if entity.ffmpeg_callback_id is not None:
            data.setdefault("callback_id", entity.ffmpeg_callback_id)
        return data

    @staticmethod
    def sync_entities_to_db():
        try:
            for entity in list(QueueEntity.entity_list):
                LogicQueue._ensure_db_entity(entity.info)
                LogicQueue._update_db_from_runtime(entity, LogicQueue._make_runtime_snapshot(entity))
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def _set_entity_status(entity, status, percent=0, data=None):
        entity.ffmpeg_status = int(status)
        entity.ffmpeg_status_kor = FFMPEG_STATUS_KOR.get(int(status), str(status))
        entity.ffmpeg_percent = int(percent or 0)
        entity.status = int(status)
        entity.ffmpeg_arg = {"status": int(status), "data": data or {}}
        if data is not None:
            entity.ffmpeg_idx = data.get("idx")
            if data.get("callback_id") is not None:
                entity.ffmpeg_callback_id = str(data.get("callback_id"))

        try:
            from . import plugin

            plugin.socketio_callback(
                "status",
                {
                    "plugin_id": entity.entity_id,
                    "status": entity.ffmpeg_status_kor,
                    "data": {
                        "percent": entity.ffmpeg_percent,
                        "current_speed": "" if data is None else data.get("current_speed", ""),
                    },
                },
            )
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def ffmpeg_callback(**arg):
        try:
            callback_id = str(arg.get("callback_id", ""))
            data = arg.get("data") or {}
            if callback_id == "":
                return

            entity = QueueEntity.get_entity_by_entity_id(callback_id)
            if entity is None:
                return

            status = int(arg.get("status", data.get("status", entity.ffmpeg_status)))
            percent = int(data.get("percent", entity.ffmpeg_percent))
            LogicQueue._set_entity_status(entity, status, percent, data)
            LogicQueue._update_db_from_runtime(entity, data)

            if status in FINAL_STATUS and entity.ffmpeg_finalized is False:
                entity.ffmpeg_finalized = True
                LogicQueue.current_ffmpeg_count = max(0, LogicQueue.current_ffmpeg_count - 1)
                LogicQueue._remove_completed_entity(entity, status)
                from . import plugin

                plugin.socketio_list_refresh()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def _update_db_from_runtime(entity, data):
        with F.app.app_context():
            episode = db.session.query(ModelLinkkf).filter_by(episodecode=entity.info["code"]).with_for_update().first()
            if episode is None:
                return

            status = int(data.get("status", entity.ffmpeg_status))
            episode.ffmpeg_status = status
            episode.filename = data.get("filename", entity.info.get("filename"))
            episode.save_path = data.get("save_path", LogicQueue._make_save_path(entity.info))

            if status in ACTIVE_STATUS:
                episode.status = "downloading"

            if status == 7:
                episode.completed = True
                episode.completed_time = datetime.now()
                episode.end_time = datetime.now()
                if episode.start_time is not None and episode.end_time is not None:
                    episode.download_time = int((episode.end_time - episode.start_time).total_seconds())
                episode.filesize = data.get("filesize")
                episode.filesize_str = data.get("filesize_str")
                episode.download_speed = data.get("download_speed")
                episode.status = "completed"
            elif status == 6:
                episode.user_abort = True
                episode.status = "canceled"
            elif status == 9:
                episode.pf_abort = True
                episode.pf = int(data.get("current_pf_count", 0))
                episode.status = "error"
            elif status in {1, 2, 3, 4, 8, 10, 11, 12}:
                episode.etc_abort = status
                episode.status = "error"
            elif status == 100:
                episode.completed = True
                episode.completed_time = datetime.now()
                episode.status = "completed"

            db.session.commit()

    @staticmethod
    def _download_subtitle(video_info, save_path, filename, headers):
        try:
            subtitle_url = video_info[2]
            if subtitle_url in [None, ""]:
                return

            if subtitle_url.startswith("http"):
                vtt_url = subtitle_url
            else:
                match = re.match(r"(https?://[^/]+)", str(video_info[1] or ""))
                if match is None:
                    return
                vtt_url = match.group(1) + subtitle_url

            srt_filepath = os.path.join(save_path, filename.replace(".mp4", ".ko.srt"))
            if os.path.exists(srt_filepath):
                return

            response = requests.get(vtt_url, headers=headers, timeout=30)
            if response.status_code != 200:
                return

            srt_data = convert_vtt_to_srt(response.text)
            write_file(srt_data, srt_filepath)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def _remove_from_pending_queue(entity_id):
        if LogicQueue.download_queue is None:
            return
        with LogicQueue.download_queue.mutex:
            LogicQueue.download_queue.queue = deque(
                item
                for item in list(LogicQueue.download_queue.queue)
                if str(item.entity_id) != str(entity_id)
            )

    @staticmethod
    def _remove_entity_only(entity):
        if entity is None:
            return
        QueueEntity.entity_list = [
            item for item in QueueEntity.entity_list if str(item.entity_id) != str(entity.entity_id)
        ]

    @staticmethod
    def _remove_completed_entity(entity, status):
        if entity is None:
            return
        if int(status) in {7, 100}:
            LogicQueue._remove_entity_only(entity)

    @staticmethod
    def _prepare_download(entity):
        from .logic_linkkf import LogicLinkkf

        LogicQueue._ensure_db_entity(entity.info)
        entity.url = LogicLinkkf.get_video_url(entity.info["url"])
        logger.debug("resolved video url: %s", entity.url)

        if entity.url is None or entity.url[0] is None:
            LogicQueue._set_entity_status(entity, 1, 0, {})
            LogicQueue._update_db_from_runtime(entity, {"status": 1})
            return None

        save_path = LogicQueue._make_save_path(entity.info)
        os.makedirs(save_path, exist_ok=True)
        target_path = os.path.join(save_path, entity.info["filename"])

        if os.path.exists(target_path):
            LogicQueue._set_entity_status(entity, 100, 100, {"percent": 100})
            LogicQueue._update_db_from_runtime(
                entity,
                {
                    "status": 100,
                    "filename": entity.info["filename"],
                    "save_path": save_path,
                    "percent": 100,
                },
            )
            entity.ffmpeg_finalized = True
            LogicQueue._remove_completed_entity(entity, 100)
            return None

        headers = LogicQueue._make_headers(entity.url)
        LogicQueue._download_subtitle(entity.url, save_path, entity.info["filename"], headers)

        return {
            "video_url": entity.url[0],
            "save_path": save_path,
            "headers": headers,
        }

    @staticmethod
    def download_thread_function():
        while True:
            entity = None
            try:
                while LogicQueue.current_ffmpeg_count >= int(ModelSetting.get("max_ffmpeg_process_count")):
                    time.sleep(1)

                entity = LogicQueue.download_queue.get()
                if entity is None or entity.cancel:
                    continue

                prepared = LogicQueue._prepare_download(entity)
                if prepared is None:
                    continue

                ffmpeg_instance = SupportFfmpeg(
                    prepared["video_url"],
                    entity.info["filename"],
                    save_path=prepared["save_path"],
                    headers=prepared["headers"],
                    callback_id=str(entity.entity_id),
                    callback_function=LogicQueue.ffmpeg_callback,
                )
                data = ffmpeg_instance.start()
                logger.debug("ffmpeg direct download start: %s", data)

                LogicQueue.current_ffmpeg_count += 1
                entity.ffmpeg_callback_id = str(data.get("callback_id"))
                LogicQueue._set_entity_status(
                    entity,
                    data.get("status", 0),
                    data.get("percent", 0),
                    data,
                )
                LogicQueue._update_db_from_runtime(entity, data)

                from . import plugin

                plugin.socketio_list_refresh()
            except Exception as e:
                if entity is not None:
                    LogicQueue._set_entity_status(entity, 4, entity.ffmpeg_percent, {})
                    LogicQueue._update_db_from_runtime(entity, {"status": 4})
                logger.error("Exception:%s", e)
                logger.error(traceback.format_exc())
            finally:
                if entity is not None and LogicQueue.download_queue is not None:
                    try:
                        LogicQueue.download_queue.task_done()
                    except Exception:
                        pass

    @staticmethod
    def monitor_thread_function():
        while True:
            try:
                for entity in list(QueueEntity.entity_list):
                    if entity.ffmpeg_callback_id in [None, ""] or entity.ffmpeg_finalized:
                        continue

                    instance = SupportFfmpeg.get_instance_by_callback_id(entity.ffmpeg_callback_id)
                    if instance is None:
                        continue

                    data = instance.get_data()
                    status = int(data.get("status", entity.ffmpeg_status))
                    percent = int(data.get("percent", entity.ffmpeg_percent))

                    if status != entity.ffmpeg_status or percent != entity.ffmpeg_percent:
                        LogicQueue._set_entity_status(entity, status, percent, data)
                        LogicQueue._update_db_from_runtime(entity, data)

                    if status in FINAL_STATUS:
                        entity.ffmpeg_finalized = True
                        LogicQueue.current_ffmpeg_count = max(0, LogicQueue.current_ffmpeg_count - 1)
                        LogicQueue._remove_completed_entity(entity, status)
                        from . import plugin

                        plugin.socketio_list_refresh()
            except Exception as e:
                logger.error("Exception:%s", e)
                logger.error(traceback.format_exc())

            time.sleep(1)

    @staticmethod
    def add_queue(info):
        try:
            db_entity = ModelLinkkf.get_by_linkkf_id(info["code"])
            existing = None
            for item in QueueEntity.entity_list:
                if item.info["code"] == info["code"] and item.ffmpeg_status not in FINAL_STATUS:
                    existing = item
                    break

            if existing is not None:
                return "queue_exist"

            if db_entity is not None and db_entity.status == "completed":
                return "db_completed"

            LogicQueue._ensure_db_entity(info, reset_state=True)

            entity = QueueEntity(info)
            LogicQueue.download_queue.put(entity)

            from . import plugin

            plugin.socketio_list_refresh()

            if db_entity is None:
                return "enqueue_db_append"
            return "enqueue_db_exist"
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def _stop_entity(entity):
        if entity is None or entity.ffmpeg_callback_id in [None, ""]:
            return {"ret": "refresh"}

        SupportFfmpeg.stop_by_callback_id(entity.ffmpeg_callback_id)
        instance = SupportFfmpeg.get_instance_by_callback_id(entity.ffmpeg_callback_id)
        data = instance.get_data() if instance is not None else {}
        if data:
            LogicQueue._set_entity_status(
                entity,
                data.get("status", 6),
                data.get("percent", entity.ffmpeg_percent),
                data,
            )
            LogicQueue._update_db_from_runtime(entity, data)
        else:
            LogicQueue._set_entity_status(entity, 6, entity.ffmpeg_percent, {})
            LogicQueue._update_db_from_runtime(entity, {"status": 6})
        entity.ffmpeg_finalized = True
        LogicQueue.current_ffmpeg_count = max(0, LogicQueue.current_ffmpeg_count - 1)
        return {"ret": "refresh"}

    @staticmethod
    def program_auto_command(req):
        ret = {}
        try:
            entity_id = req.form.get("entity_id", "-1")
            command = req.form["command"]
            entity = QueueEntity.get_entity_by_entity_id(entity_id)

            if command == "cancel":
                if entity is None:
                    return {"ret": "refresh"}
                if entity.ffmpeg_status == -1:
                    entity.cancel = True
                    entity.ffmpeg_finalized = True
                    entity.ffmpeg_status = 6
                    entity.ffmpeg_status_kor = FFMPEG_STATUS_KOR[6]
                    ret["ret"] = "refresh"
                elif entity.ffmpeg_status in ACTIVE_STATUS:
                    ret = LogicQueue._stop_entity(entity)
                else:
                    ret["ret"] = "notify"
                    ret["log"] = "다운로드 중인 상태가 아닙니다."
            elif command == "delete":
                if entity is None:
                    return {"ret": "refresh"}
                if entity.ffmpeg_status == -1:
                    entity.cancel = True
                    entity.ffmpeg_finalized = True
                    LogicQueue._remove_from_pending_queue(entity.entity_id)
                elif entity.ffmpeg_status in ACTIVE_STATUS:
                    LogicQueue._stop_entity(entity)
                LogicQueue._remove_entity_only(entity)
                ret["ret"] = "refresh"
            elif command == "reset":
                if LogicQueue.download_queue is not None:
                    with LogicQueue.download_queue.mutex:
                        LogicQueue.download_queue.queue.clear()
                for item in list(QueueEntity.entity_list):
                    if item.ffmpeg_status in ACTIVE_STATUS:
                        LogicQueue._stop_entity(item)
                QueueEntity.entity_list = []
                LogicQueue.current_ffmpeg_count = 0
                ret["ret"] = "refresh"
            elif command == "delete_completed":
                QueueEntity.entity_list = [
                    item for item in QueueEntity.entity_list if item.ffmpeg_status not in FINAL_STATUS
                ]
                ret["ret"] = "refresh"
            else:
                ret["ret"] = "notify"
                ret["log"] = f"지원하지 않는 명령: {command}"

            from . import plugin

            plugin.socketio_list_refresh()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            ret["ret"] = "notify"
            ret["log"] = str(e)
        return ret
