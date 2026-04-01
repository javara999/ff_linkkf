# -*- coding: utf-8 -*-
import os
import traceback

from framework import F, Job, db, get_logger, path_data, scheduler
from support import SupportFile

from .logic_linkkf import LogicLinkkf
from .logic_queue import LogicQueue
from .model import ModelLinkkf, ModelSetting


package_name = __name__.split(".")[0]
logger = get_logger(package_name)


class Logic(object):
    db_default = {
        "linkkf_url": "https://linkkf.tv",
        "download_path": os.path.join(path_data, "linkkf"),
        "linkkf_auto_make_folder": "True",
        "linkkf_auto_make_season_folder": "True",
        "linkkf_finished_insert": "[완결]",
        "include_date": "False",
        "date_option": "0",
        "auto_make_folder": "True",
        "max_ffmpeg_process_count": "4",
        "auto_interval": "* 20 * * *",
        "auto_start": "False",
        "whitelist_program": "",
    }

    @staticmethod
    def db_init():
        try:
            with F.app.app_context():
                logger.debug(Logic.db_default.items())
                for key, value in Logic.db_default.items():
                    logger.debug(f"{key}: {value}")
                    if db.session.query(ModelSetting).filter_by(key=key).count() == 0:
                        db.session.add(ModelSetting(key, value))
                db.session.commit()
                Logic.db_migration()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def plugin_load():
        try:
            logger.debug("%s plugin_load", package_name)
            Logic.db_init()

            if ModelSetting.get("auto_start") == "True":
                Logic.scheduler_start()

            from .plugin import plugin_info

            SupportFile.write_json(
                os.path.join(os.path.dirname(__file__), "info.json"),
                plugin_info,
            )
            LogicQueue.queue_start()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def plugin_unload():
        try:
            logger.debug("%s plugin_unload", package_name)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def db_migration():
        logger.debug("db_migration::=======================")
        try:
            migrated = ModelLinkkf.migrate_existing_rows()
            logger.debug("ModelLinkkf migrate_existing_rows: %s", migrated)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_start():
        try:
            interval = ModelSetting.get("auto_interval")
            job = Job(
                package_name,
                package_name,
                interval,
                Logic.scheduler_function,
                "linkkf 다운로드",
                True,
            )
            scheduler.add_job_instance(job)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_stop():
        try:
            scheduler.remove_job(package_name)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def setting_save(req):
        try:
            for key, value in req.form.items():
                logger.debug("Key:%s Value:%s", key, value)
                entity = (
                    db.session.query(ModelSetting)
                    .filter_by(key=key)
                    .with_for_update()
                    .first()
                )
                entity.value = value
            db.session.commit()
            return True
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            logger.error("key:%s value:%s", key, value)
            return False

    @staticmethod
    def scheduler_function():
        try:
            LogicLinkkf.scheduler_function()
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
