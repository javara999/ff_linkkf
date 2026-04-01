# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime

from sqlalchemy import desc, or_

from .setup import *


ModelSetting = P.ModelSetting


class ModelLinkkfProgram(ModelBase):
    P = P
    __tablename__ = "linkkf_program"
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    contents_json = db.Column(db.JSON)
    created_time = db.Column(db.DateTime)
    programcode = db.Column(db.String)
    save_folder = db.Column(db.String)
    season = db.Column(db.Integer)

    def __init__(self, data):
        self.created_time = datetime.now()
        self.programcode = data["code"]
        self.save_folder = data["title"]
        self.season = data["season"]

    def set_info(self, data):
        self.contents_json = data
        self.programcode = data["code"]
        self.save_folder = data["save_folder"]
        self.season = data["season"]


class ModelLinkkf(ModelBase):
    P = P
    __tablename__ = "linkkf_auto_episode"
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    contents_json = db.Column(db.JSON)
    created_time = db.Column(db.DateTime)
    completed_time = db.Column(db.DateTime)

    programcode = db.Column(db.String)
    episodecode = db.Column(db.String)
    filename = db.Column(db.String)
    duration = db.Column(db.Integer)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    download_time = db.Column(db.Integer)
    completed = db.Column(db.Boolean)
    user_abort = db.Column(db.Boolean)
    pf_abort = db.Column(db.Boolean)
    etc_abort = db.Column(db.Integer)
    ffmpeg_status = db.Column(db.Integer)
    temp_path = db.Column(db.String)
    save_path = db.Column(db.String)
    pf = db.Column(db.Integer)
    retry = db.Column(db.Integer)
    filesize = db.Column(db.Integer)
    filesize_str = db.Column(db.String)
    download_speed = db.Column(db.String)
    call = db.Column(db.String)
    status = db.Column(db.String)
    linkkf_info = db.Column(db.JSON)

    def __init__(self, call, info):
        self.created_time = datetime.now()
        self.completed = False
        self.start_time = datetime.now()
        self.user_abort = False
        self.pf_abort = False
        self.etc_abort = 0
        self.ffmpeg_status = -1
        self.pf = 0
        self.retry = 0
        self.call = call
        self.set_info(info)

    def as_dict(self):
        ret = super().as_dict()
        if ret.get("status") in [None, ""]:
            if self.completed is True:
                ret["status"] = "completed"
            elif self.user_abort is True:
                ret["status"] = "canceled"
            elif self.pf_abort is True or (self.etc_abort is not None and int(self.etc_abort) > 0):
                ret["status"] = "error"
            elif self.ffmpeg_status in [0, 5]:
                ret["status"] = "downloading"
        ret["created_time"] = self.created_time.strftime("%Y-%m-%d %H:%M:%S")
        ret["completed_time"] = (
            self.completed_time.strftime("%Y-%m-%d %H:%M:%S")
            if self.completed_time is not None
            else None
        )
        return ret

    def set_info(self, data):
        self.contents_json = data
        self.programcode = data["program_code"]
        self.episodecode = data["code"]
        self.filename = data.get("filename", self.filename)
        self.linkkf_info = data
        if self.status in [None, ""]:
            self.status = "waiting"

    @staticmethod
    def _normalize_json_data(data):
        if isinstance(data, dict):
            return data
        if isinstance(data, str) and data.strip() != "":
            try:
                return json.loads(data)
            except Exception:
                return {}
        return {}

    @classmethod
    def sync_completed_from_filesystem(cls):
        with F.app.app_context():
            changed = 0
            rows = F.db.session.query(cls).filter(
                or_(cls.status != "completed", cls.status.is_(None), cls.completed.is_(False))
            ).all()
            for row in rows:
                info = cls._normalize_json_data(row.linkkf_info) or cls._normalize_json_data(row.contents_json)
                save_path = row.save_path or info.get("save_path")
                filename = row.filename or info.get("filename")
                if not save_path or not filename:
                    continue
                fullpath = os.path.join(save_path, filename)
                if os.path.exists(fullpath) is False:
                    continue
                row.completed = True
                row.user_abort = False
                row.pf_abort = False
                row.etc_abort = 0
                row.ffmpeg_status = 7 if row.ffmpeg_status in [None, -1, 0, 5] else row.ffmpeg_status
                row.status = "completed"
                file_time = datetime.fromtimestamp(os.path.getmtime(fullpath))
                if row.end_time is None:
                    row.end_time = file_time
                if row.completed_time is None:
                    row.completed_time = file_time
                changed += 1
            if changed > 0:
                F.db.session.commit()
            return changed

    @classmethod
    def migrate_existing_rows(cls):
        with F.app.app_context():
            changed = 0
            rows = F.db.session.query(cls).all()
            for row in rows:
                info = cls._normalize_json_data(row.contents_json) or cls._normalize_json_data(row.linkkf_info)
                updated = False
                if row.programcode in [None, ""] and info.get("program_code"):
                    row.programcode = info.get("program_code")
                    updated = True
                if row.episodecode in [None, ""] and info.get("code"):
                    row.episodecode = info.get("code")
                    updated = True
                if row.filename in [None, ""] and info.get("filename"):
                    row.filename = info.get("filename")
                    updated = True
                if row.linkkf_info in [None, {}] and info:
                    row.linkkf_info = info
                    updated = True
                if row.status in [None, ""]:
                    if row.completed is True:
                        row.status = "completed"
                    elif row.user_abort is True:
                        row.status = "canceled"
                    elif row.pf_abort is True or (row.etc_abort is not None and int(row.etc_abort) > 0):
                        row.status = "error"
                    elif row.ffmpeg_status in [0, 5]:
                        row.status = "downloading"
                    else:
                        row.status = "waiting"
                    updated = True
                if updated:
                    changed += 1
            if changed > 0:
                F.db.session.commit()
            changed += cls.sync_completed_from_filesystem()
            return changed

    @classmethod
    def web_list(cls, req):
        with F.app.app_context():
            ret = {}
            cls.sync_completed_from_filesystem()
            page = int(req.form["page"]) if "page" in req.form else 1
            page_size = 30
            search = req.form["search_word"] if "search_word" in req.form else req.form.get("keyword", "")
            option = req.form["option"] if "option" in req.form else req.form.get("option1", "finished")
            order = req.form["order"] if "order" in req.form else "desc"

            query = cls.make_query(search=search, order=order, option=option)
            count = query.count()
            query = query.limit(page_size).offset((page - 1) * page_size)
            lists = query.all()
            ret["list"] = [item.as_dict() for item in lists]
            ret["paging"] = cls.get_paging_info(count, page, page_size)
            return ret

    @classmethod
    def get_by_linkkf_id(cls, linkkf_id):
        with F.app.app_context():
            return F.db.session.query(cls).filter_by(episodecode=linkkf_id).first()

    @classmethod
    def make_query(cls, search="", order="desc", option="all"):
        query = F.db.session.query(cls)
        if search is not None and search != "":
            if "|" in search:
                conditions = []
                for token in [x.strip() for x in search.split("|") if x.strip()]:
                    conditions.append(cls.filename.like(f"%{token}%"))
                    conditions.append(cls.programcode.like(f"%{token}%"))
                if conditions:
                    query = query.filter(or_(*conditions))
            elif "," in search:
                for token in [x.strip() for x in search.split(",") if x.strip()]:
                    query = query.filter(
                        or_(
                            cls.filename.like(f"%{token}%"),
                            cls.programcode.like(f"%{token}%"),
                        )
                    )
            else:
                query = query.filter(
                    or_(
                        cls.filename.like(f"%{search}%"),
                        cls.programcode.like(f"%{search}%"),
                    )
                )
        if option == "completed":
            query = query.filter(or_(cls.status == "completed", cls.completed.is_(True)))
        elif option == "canceled":
            query = query.filter(or_(cls.status == "canceled", cls.user_abort.is_(True)))
        elif option == "error":
            query = query.filter(
                or_(
                    cls.status == "error",
                    cls.pf_abort.is_(True),
                    cls.etc_abort > 0,
                )
            )
        elif option == "finished":
            query = query.filter(
                or_(
                    cls.status.in_(["completed", "error", "canceled"]),
                    cls.completed.is_(True),
                    cls.user_abort.is_(True),
                    cls.pf_abort.is_(True),
                    cls.etc_abort > 0,
                )
            )
        elif option == "downloading":
            query = query.filter(cls.status == "downloading")
        if order == "desc":
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(cls.id)
        return query
