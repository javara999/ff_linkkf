import asyncio
import json
import re
import threading
import traceback
import urllib.parse

import requests
from flask import Response, jsonify, render_template, stream_with_context
from plugin import PluginModuleBase, default_route_socketio_module
from framework import F

from .logic import Logic
from .logic_linkkf import LogicLinkkf
from .logic_queue import LogicQueue, QueueEntity
from .model import ModelLinkkf
from .setup import P


class ModuleBasic(PluginModuleBase):
    template_prefix = "linkkf"

    def __init__(self, P):
        super(ModuleBasic, self).__init__(P, name="main")
        default_route_socketio_module(self)

    @staticmethod
    def _make_proxy_url(target, referer):
        return (
            f"/{P.package_name}/normal/proxy"
            f"?target={urllib.parse.quote(str(target), safe='')}"
            f"&referer={urllib.parse.quote(str(referer or ''), safe='')}"
        )

    @staticmethod
    def _get_proxy_headers(referer):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": referer or P.ModelSetting.get("linkkf_url"),
            "Origin": urllib.parse.urlsplit(referer or P.ModelSetting.get("linkkf_url")).scheme
            + "://"
            + urllib.parse.urlsplit(referer or P.ModelSetting.get("linkkf_url")).netloc,
        }

    @staticmethod
    def _rewrite_m3u8(content, target_url, referer):
        def replace_uri_attr(line):
            def repl(match):
                absolute = urllib.parse.urljoin(target_url, match.group(1))
                proxied = ModuleBasic._make_proxy_url(absolute, referer)
                return f'URI="{proxied}"'

            return re.sub(r'URI="([^"]+)"', repl, line)

        lines = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line == "":
                lines.append(raw_line)
                continue
            if line.startswith("#"):
                lines.append(replace_uri_attr(raw_line))
                continue
            absolute = urllib.parse.urljoin(target_url, line)
            lines.append(ModuleBasic._make_proxy_url(absolute, referer))
        return "\n".join(lines)

    def process_menu(self, sub, req):
        if sub == "log":
            return render_template("log.html", package=self.P.package_name)

        arg = self.P.ModelSetting.to_dict() if self.P.ModelSetting is not None else {}
        arg["package_name"] = self.P.package_name
        arg["sub"] = sub
        arg["template_name"] = f"{self.template_prefix}_{sub}"

        if sub == "setting":
            arg["whitelist_program"] = (
                self.P.ModelSetting.get("whitelist_program")
                if self.P.ModelSetting is not None
                else ""
            ) or ""
            arg["scheduler"] = str(F.scheduler.is_include(self.P.package_name))
            arg["is_running"] = str(F.scheduler.is_running(self.P.package_name))
        elif sub in ["request", "queue", "list"]:
            arg["current_code"] = (
                LogicLinkkf.current_data["code"]
                if LogicLinkkf.current_data is not None
                else ""
            )

        return render_template(f"{self.template_prefix}_{sub}.html", arg=arg)

    def process_ajax(self, sub, req):
        try:
            if sub == "scheduler_toggle":
                go = req.form["scheduler"]
                if go == "true":
                    Logic.scheduler_start()
                else:
                    Logic.scheduler_stop()
                return jsonify(go)
            if sub == "execute_once":
                threading.Thread(target=Logic.scheduler_function, daemon=True).start()
                return jsonify({"ret": "success"})
            if sub == "analysis":
                code = req.form["code"]
                data = LogicLinkkf.get_title_info(code)
                if data["ret"] == "error":
                    return jsonify(data)
                return jsonify({"ret": "success", "data": data})
            if sub == "play":
                episode_url = req.form["url"]
                play_title = req.form.get("title", "LinkKF")
                return jsonify(
                    {
                        "ret": "success",
                        "data": {
                            "play_url": (
                                f"/{self.P.package_name}/normal/play"
                                f"?url={urllib.parse.quote(str(episode_url), safe='')}"
                                f"&title={urllib.parse.quote(str(play_title), safe='')}"
                            )
                        },
                    }
                )
            if sub == "play_latest":
                code = req.form["code"]
                data = LogicLinkkf.get_title_info(code)
                if data["ret"] == "error":
                    return jsonify(data)
                if "episode" not in data or len(data["episode"]) == 0:
                    return jsonify({"ret": "error", "log": "최신 화 정보를 찾지 못했습니다."})
                latest_episode = data["episode"][0]
                latest_title = f"{data['title']} - {latest_episode['title']}"
                return jsonify(
                    {
                        "ret": "success",
                        "data": {
                            "play_url": (
                                f"/{self.P.package_name}/normal/play"
                                f"?url={urllib.parse.quote(str(latest_episode['url']), safe='')}"
                                f"&title={urllib.parse.quote(str(latest_title), safe='')}"
                            ),
                        },
                    }
                )
            if sub == "search":
                query = req.form["query"]
                return jsonify(LogicLinkkf.get_search_result(str(query)))
            if sub == "anime_list":
                page = req.form["page"]
                cate = req.form["type"]
                return jsonify(LogicLinkkf.get_anime_list_info(cate, page))
            if sub == "airing_list":
                return jsonify(LogicLinkkf.get_airing_info())
            if sub == "get_airing_code":
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                data = loop.run_until_complete(LogicLinkkf.get_airing_code())
                return jsonify({"ret": "success", "data": data})
            if sub == "screen_movie_list":
                page = req.form["page"]
                return jsonify(LogicLinkkf.get_screen_movie_info(page))
            if sub == "complete_anilist":
                page = req.form["page"]
                return jsonify(LogicLinkkf.get_complete_anilist_info(page))
            if sub == "apply_new_title":
                return jsonify(LogicLinkkf.apply_new_title(req.form["new_title"]))
            if sub == "apply_new_season":
                return jsonify(LogicLinkkf.apply_new_season(req.form["new_season"]))
            if sub == "add_whitelist":
                payload = req.get_json()
                if payload is None:
                    ret = LogicLinkkf.add_whitelist()
                else:
                    ret = LogicLinkkf.add_whitelist(payload)
                return jsonify(ret)
            if sub == "add_queue":
                code = req.form["code"]
                info = LogicLinkkf.get_info_by_code(code)
                if info is not None:
                    return jsonify({"ret": LogicQueue.add_queue(info)})
                return jsonify({"ret": "no_data"})
            if sub == "add_queue_checked_list":
                code_list = req.form["code"].split(",")
                count = 0
                for code in code_list:
                    info = LogicLinkkf.get_info_by_code(code)
                    if info is not None:
                        LogicQueue.add_queue(info)
                        count += 1
                return jsonify({"ret": "success", "log": str(count)})
            if sub == "down_subtitle_list":
                code_list = req.form["code"].split(",")
                count = 0
                for code in code_list:
                    info = LogicLinkkf.get_info_by_code(code)
                    if info is not None:
                        LogicLinkkf.download_subtitle(info)
                        count += 1
                return jsonify({"ret": "success", "log": str(count)})
            if sub == "program_auto_command":
                return jsonify(LogicQueue.program_auto_command(req))
            if sub == "web_list":
                LogicQueue.sync_entities_to_db()
                return jsonify(ModelLinkkf.web_list(req))
            if sub == "db_remove":
                return jsonify(ModelLinkkf.delete_by_id(req.form["id"]))
            if sub == "reset_db":
                res = LogicLinkkf.reset_db()
                return jsonify({"ret": "success" if res else "error"})
        except Exception as e:
            self.P.logger.error(f"Exception:{str(e)}")
            self.P.logger.error(traceback.format_exc())
            return jsonify({"ret": "error", "log": str(e)})
        return jsonify({"ret": "error", "log": f"unsupported ajax: {sub}"})

    def process_normal(self, sub, req):
        try:
            if sub == "play":
                episode_url = req.args.get("url", "").strip()
                play_title = req.args.get("title", "LinkKF").strip()
                video_info = LogicLinkkf.get_video_url(episode_url)
                if video_info is None or video_info[0] in [None, ""]:
                    return f"재생 URL을 가져오지 못했습니다: {episode_url}", 500

                referer = video_info[1] or self.P.ModelSetting.get("linkkf_url")
                data = {
                    "play_title": play_title or "LinkKF",
                    "play_source_src": self._make_proxy_url(video_info[0], referer),
                    "play_source_type": "application/x-mpegURL" if ".m3u8" in str(video_info[0]).lower() else "video/mp4",
                    "play_subtitle_src": "",
                }
                if len(video_info) > 2 and video_info[2] not in [None, ""]:
                    data["play_subtitle_src"] = self._make_proxy_url(video_info[2], referer)
                return render_template("videojs.html", data=data)

            if sub == "proxy":
                target = req.args.get("target", "").strip()
                referer = req.args.get("referer", self.P.ModelSetting.get("linkkf_url")).strip()
                if target == "":
                    return "missing target", 400

                headers = self._get_proxy_headers(referer)
                if req.headers.get("Range") is not None:
                    headers["Range"] = req.headers.get("Range")
                upstream = requests.get(target, headers=headers, stream=True, timeout=30)
                content_type = upstream.headers.get("content-type", "")

                if upstream.status_code >= 400:
                    return Response(
                        upstream.content,
                        status=upstream.status_code,
                        content_type=content_type or "text/plain",
                    )

                if ".m3u8" in target.lower() or "mpegurl" in content_type.lower():
                    text = upstream.text
                    rewritten = self._rewrite_m3u8(text, target, referer)
                    return Response(
                        rewritten,
                        content_type=content_type or "application/vnd.apple.mpegurl",
                    )

                def generate():
                    try:
                        for chunk in upstream.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                yield chunk
                    finally:
                        upstream.close()

                response = Response(
                    stream_with_context(generate()),
                    status=upstream.status_code,
                    content_type=content_type or "application/octet-stream",
                )
                if upstream.headers.get("Accept-Ranges") is not None:
                    response.headers["Accept-Ranges"] = upstream.headers.get("Accept-Ranges")
                if upstream.headers.get("Content-Length") is not None:
                    response.headers["Content-Length"] = upstream.headers.get("Content-Length")
                if upstream.headers.get("Content-Range") is not None:
                    response.headers["Content-Range"] = upstream.headers.get("Content-Range")
                return response
        except Exception as e:
            self.P.logger.error(f"Exception:{str(e)}")
            self.P.logger.error(traceback.format_exc())
            return f"playback proxy error: {e}", 500
        return "unsupported normal route", 404

    def plugin_load(self):
        Logic.plugin_load()

    def plugin_unload(self):
        Logic.plugin_unload()

    def setting_save_after(self, change_list):
        if "linkkf_url" in change_list:
            LogicLinkkf.referer = None
            LogicLinkkf.headers["Referer"] = self.P.ModelSetting.get("linkkf_url")

    def socketio_connect(self):
        data = json.loads(json.dumps([item.__dict__ for item in QueueEntity.entity_list], default=str))
        self.socketio_callback("on_connect", data, encoding=False)

    def socketio_list_refresh(self):
        data = json.loads(json.dumps([item.__dict__ for item in QueueEntity.entity_list], default=str))
        self.socketio_callback("list_refresh", data, encoding=False)
