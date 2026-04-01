# -*- coding: utf-8 -*-
#########################################################
# python
import asyncio
import os
import sys
import traceback
import time
import re
import random
import urllib

import json

import cloudscraper
import requests
from bs4 import BeautifulSoup
from requests_cache import CachedSession
from lxml import html

from .lib.utils import linkkf_async_timeit

# import snoop
# from snoop import spy

from framework import db, get_logger
from framework.util import Util

# 패키지
# from .plugin import package_name, logger
# from anime_downloader.logic_ohli24 import ModelOhli24Item
from .model import ModelSetting, ModelLinkkf, ModelLinkkfProgram
from .logic_queue import LogicQueue
from .subtitle_util import convert_vtt_to_srt, write_file

#########################################################
package_name = __name__.split(".")[0]
logger = get_logger(package_name)
cache_path = os.path.dirname(__file__)


def _fallback_change_text_for_use_filename(value):
    text = str(value or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(".")
    return text


if hasattr(Util, "change_text_for_use_filename") is False:
    Util.change_text_for_use_filename = staticmethod(_fallback_change_text_for_use_filename)


# requests_cache.install_cache("linkkf_cache", backend="sqlite", expire_after=300)


class LogicLinkkf(object):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/104.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://linkkf.tv",
        # "Cookie": "SL_G_WPT_TO=ko; SL_GWPT_Show_Hide_tmp=1; SL_wptGlobTipTmp=1",
    }

    session = None
    referer = None
    current_data = None

    @staticmethod
    def _parse_total_page(soup):
        max_page = 1
        for link in soup.select('a[href*="/page/"]'):
            href = link.get("href", "")
            match = re.search(r"/page/(\d+)/?$", href)
            if match:
                max_page = max(max_page, int(match.group(1)))
        return max_page

    @staticmethod
    def _parse_vod_items(soup):
        data = []
        for item in soup.select("div.vod-item"):
            link_tag = item.select_one("a.vod-item-img[href]") or item.select_one(".vod-item-title a[href]")
            title_tag = item.select_one(".vod-item-title strong") or item.select_one(".vod-item-title a")
            image_tag = item.select_one(".img-wrapper")

            if link_tag is None or title_tag is None:
                continue

            href = link_tag.get("href", "").strip()
            title = title_tag.get_text(" ", strip=True).strip()
            if href == "" or title == "":
                continue

            code_match = re.search(r"/ani/(\d+)/?", href)
            if code_match is None:
                code_match = re.search(r"(\d+)", href)
            if code_match is None:
                continue

            chapter = ""
            for selector in [".vod-item-status", ".vod-item-desc strong", ".vod-item-desc"]:
                node = item.select_one(selector)
                if node is None:
                    continue
                text = node.get_text(" ", strip=True).replace(" .", "").strip(". ").strip()
                if text != "":
                    chapter = text
                    break

            image_link = ""
            if image_tag is not None:
                image_link = image_tag.get("data-original", "").strip()

            data.append(
                {
                    "link": urllib.parse.urljoin(ModelSetting.get("linkkf_url"), href),
                    "code": code_match.group(1),
                    "title": title,
                    "image_link": image_link,
                    "chapter": chapter,
                }
            )
        return data

    @staticmethod
    def _get_list_page(path, page=1):
        if page in [None, 1, "1"]:
            return f"{ModelSetting.get('linkkf_url').rstrip('/')}{path}"
        return f"{ModelSetting.get('linkkf_url').rstrip('/')}{path}page/{page}/"

    @staticmethod
    def _get_list_response(path, page=1):
        url = LogicLinkkf._get_list_page(path, page)
        html_content = LogicLinkkf.get_html(url, cached=False)
        soup = BeautifulSoup(html_content, "html.parser")
        items = LogicLinkkf._parse_vod_items(soup)
        return {
            "ret": "success",
            "page": int(page),
            "total_page": LogicLinkkf._parse_total_page(soup),
            "episode_count": len(items),
            "episode": items,
        }

    @staticmethod
    def _get_home_response():
        url = ModelSetting.get("linkkf_url")
        html_content = LogicLinkkf.get_html(url, cached=False)
        soup = BeautifulSoup(html_content, "html.parser")
        items = LogicLinkkf._parse_vod_items(soup)[:20]
        return {
            "ret": "success",
            "page": 1,
            "total_page": 1,
            "episode_count": len(items),
            "episode": items,
        }

    @staticmethod
    def _normalize_code(code):
        value = str(code).strip()
        match = re.search(r"/(?:ani|watch)/(\d+)/", value)
        if match:
            return match.group(1)
        match = re.search(r"(\d{3,})", value)
        if match:
            return match.group(1)
        return value

    @staticmethod
    def _parse_program_title(raw_title):
        title = (raw_title or "").strip()
        match = re.search(r"^(?P<title>.*?)(?:\s+(?P<season>\d+)\s*기)?$", title)
        if match is None:
            return Util.change_text_for_use_filename(title).strip(), "1"

        season = match.group("season") or "1"
        normalized_title = (match.group("title") or title).strip()
        normalized_title = normalized_title.replace("()", "").replace("OVA", "").strip()
        normalized_title = Util.change_text_for_use_filename(normalized_title).strip()
        return normalized_title, season

    @staticmethod
    def _parse_detail_rows(soup):
        details = []
        for li in soup.select(".detail-info-desc li"):
            label_tag = li.select_one("span")
            raw_text = li.get_text(" ", strip=True)
            if raw_text == "":
                continue

            if label_tag is None:
                details.append({"info": raw_text})
                continue

            key = label_tag.get_text(" ", strip=True).replace("：", "").replace(":", "").strip()
            value = raw_text.replace(label_tag.get_text(" ", strip=True), "", 1).strip(" /")
            if key == "":
                key = "info"
            details.append({key: value})

        return details if len(details) > 0 else [{"정보없음": ""}]

    @staticmethod
    def get_html(url, cached=False):

        try:
            if LogicLinkkf.referer is None:
                LogicLinkkf.referer = f"{ModelSetting.get('linkkf_url')}"

            # return LogicLinkkf.get_html_requests(url)
            return LogicLinkkf.get_html_cloudflare(url)

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_html_requests(url, cached=False):
        if LogicLinkkf.session is None:
            if cached:
                logger.debug("cached===========++++++++++++")

                LogicLinkkf.session = CachedSession(
                    os.path.join(cache_path, "linkkf_cache"),
                    backend="sqlite",
                    expire_after=300,
                    cache_control=True,
                )
                # print(f"{cache_path}")
                # print(f"cache_path:: {LogicLinkkf.session.cache}")
            else:
                LogicLinkkf.session = requests.Session()

        LogicLinkkf.referer = f"{ModelSetting.get('linkkf_url')}"

        LogicLinkkf.headers["Referer"] = LogicLinkkf.referer

        # logger.debug(
        #     f"get_html()::LogicLinkkf.referer = {LogicLinkkf.referer}"
        # )
        page = LogicLinkkf.session.get(url, headers=LogicLinkkf.headers)
        # logger.info(f"page: {page}")

        return page.content.decode("utf8", errors="replace")

    @staticmethod
    def get_html_selenium(url, referer=None):
        from selenium.webdriver.common.by import By

        from selenium import webdriver
        from selenium_stealth import stealth
        from webdriver_manager.chrome import ChromeDriverManager

        from seleniumwire import webdriver
        import time
        import platform
        import os

        os_platform = platform.system()

        # print(os_platform)

        options = webdriver.ChromeOptions()
        # 크롬드라이버 헤더 옵션추가 (리눅스에서 실행시 필수)
        options.add_argument("start-maximized")
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        if os_platform == "Darwin":
            # 크롬드라이버 경로
            driver_bin_path = os.path.join(
                os.path.dirname(__file__), "bin", f"{os_platform}"
            )
            driver_path = f"{driver_bin_path}/chromedriver"
            driver = webdriver.Chrome(
                executable_path=driver_path, chrome_options=options
            )
            # driver = webdriver.Chrome(
            #     ChromeDriverManager().install(), chrome_options=options
            # )
        elif os_platform == "Linux":
            driver_bin_path = os.path.join(
                os.path.dirname(__file__), "bin", f"{os_platform}"
            )
            driver_path = f"{driver_bin_path}/chromedriver"
            driver = webdriver.Chrome(
                executable_path=driver_path, chrome_options=options
            )

        else:
            # driver_bin_path = os.path.join(
            #     os.path.dirname(__file__), "bin", f"{os_platform}"
            # )
            # driver_path = f"{driver_bin_path}/chromedriver"
            # driver = webdriver.Chrome(executable_path=driver_path, chrome_options=options)
            driver = webdriver.Chrome(
                ChromeDriverManager().install(), chrome_options=options
            )

        LogicLinkkf.headers["Referer"] = f"{ModelSetting.get('linkkf_url')}"

        driver.header_overrides = LogicLinkkf.headers
        # stealth(
        #     driver,
        #     languages=["en-US", "en"],
        #     vendor="Google Inc.",
        #     platform="Win32",
        #     webgl_vendor="Intel Inc.",
        #     renderer="Intel Iris OpenGL Engine",
        #     fix_hairline=True,
        # )
        driver.get(url)

        # driver.refresh()
        print(f"current_url:: {driver.current_url}")

        # time.sleep(1)
        elem = driver.find_element(By.XPATH, "//*")
        source_code = elem.get_attribute("outerHTML")

        time.sleep(3.0)

        return source_code.encode("utf-8")

    @staticmethod
    def get_html_playwright(url):
        from playwright.sync_api import sync_playwright
        import time

        try:

            start = time.time()
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/69.0.3497.100 Safari/537.36"
            )
            # from playwright_stealth import stealth_sync

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=ua,
                )
                LogicLinkkf.referer = f"{ModelSetting.get('linkkf_url')}"

                LogicLinkkf.headers["Referer"] = LogicLinkkf.referer

                logger.debug(f"headers::: {LogicLinkkf.headers}")

                context.set_extra_http_headers(LogicLinkkf.headers)

                page = context.new_page()

                page.set_extra_http_headers(LogicLinkkf.headers)
                # stealth_sync(page)
                page.goto(url, wait_until="domcontentloaded")

                # print(page.request.headers)
                # print(page.content())

                print(f"run at {time.time() - start} sec")

                return page.content()
        except ModuleNotFoundError:
            # os.system(f"pip3 install playwright")
            # os.system(f"playwright install")
            pass

    @staticmethod
    def get_html_cloudflare(url, cached=False):
        # scraper = cloudscraper.create_scraper(
        #     # disableCloudflareV1=True,
        #     # captcha={"provider": "return_response"},
        #     delay=10,
        #     browser="chrome",
        # )
        # scraper = cfscrape.create_scraper(
        #     browser={"browser": "chrome", "platform": "android", "desktop": False}
        # )

        # scraper = cloudscraper.create_scraper(
        #     browser={"browser": "chrome", "platform": "windows", "mobile": False},
        #     debug=True,
        # )
        logger.debug("cloudflare protection bypass ==================")

        user_agents_list = [
            "Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.83 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
        ]
        # ua = UserAgent(verify_ssl=False)

        LogicLinkkf.headers["User-Agent"] = random.choice(user_agents_list)

        LogicLinkkf.headers["Referer"] = LogicLinkkf.referer

        # logger.debug(f"headers:: {LogicLinkkf.headers}")

        if LogicLinkkf.session is None:
            LogicLinkkf.session = requests.Session()

        # LogicLinkkf.session = requests.Session()
        # re_sess = requests.Session()
        # logger.debug(LogicLinkkf.session)

        # sess = cloudscraper.create_scraper(
        #     # browser={"browser": "firefox", "mobile": False},
        #     browser={"browser": "chrome", "mobile": False},
        #     debug=True,
        #     sess=LogicLinkkf.session,
        #     delay=10,
        # )
        # scraper = cloudscraper.create_scraper(sess=re_sess)
        scraper = cloudscraper.create_scraper(
            # debug=True,
            delay=10,
            sess=LogicLinkkf.session,
            browser={
                "custom": "linkkf",
            },
        )

        # print(scraper.get(url, headers=LogicLinkkf.headers).content)
        # print(scraper.get(url).content)
        # return scraper.get(url, headers=LogicLinkkf.headers).content
        # logger.debug(LogicLinkkf.headers)
        return scraper.get(
            url,
            headers=LogicLinkkf.headers,
            timeout=10,
        ).content.decode("utf8", errors="replace")

    @staticmethod
    def get_video_url_from_url(url, url2):
        target = str(url2 or "").replace("&amp;", "&").strip()
        if target == "":
            return [None, None, None]

        if target.startswith("/"):
            target = urllib.parse.urljoin(url, target)

        try:
            player_html = LogicLinkkf.get_html(target)
            video_url, vtt_url = LogicLinkkf._extract_stream_config(player_html, target)
            if video_url is not None:
                return [video_url, target, vtt_url]

            server_urls = re.findall(r'data-url=["\']([^"\']+)["\']', player_html)
            for server_url in server_urls:
                next_target = server_url.replace("&amp;", "&")
                if next_target.startswith("/"):
                    next_target = urllib.parse.urljoin(target, next_target)
                nested_html = LogicLinkkf.get_html(next_target)
                video_url, vtt_url = LogicLinkkf._extract_stream_config(nested_html, next_target)
                if video_url is not None:
                    return [video_url, next_target, vtt_url]
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

        return [None, None, None]

    @staticmethod
    def apply_new_title(new_title):
        try:
            ret = {}
            if LogicLinkkf.current_data is not None:
                program = (
                    db.session.query(ModelLinkkfProgram)
                    .filter_by(programcode=LogicLinkkf.current_data["code"])
                    .first()
                )
                new_title = Util.change_text_for_use_filename(new_title)
                LogicLinkkf.current_data["save_folder"] = new_title
                program.save_folder = new_title
                db.session.commit()
                total_epi = None
                for entity in LogicLinkkf.current_data["episode"]:
                    entity["save_folder"] = new_title
                    entity["filename"] = LogicLinkkf.get_filename(
                        LogicLinkkf.current_data["save_folder"],
                        LogicLinkkf.current_data["season"],
                        entity["title"],
                        total_epi,
                    )

                return LogicLinkkf.current_data
            else:
                ret["ret"] = False
                ret["log"] = "No current data!!"
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            ret["ret"] = False
            ret["log"] = str(e)
        return ret

    @staticmethod
    def apply_new_season(new_season):
        try:
            ret = {}
            season = int(new_season)
            if LogicLinkkf.current_data is not None:
                program = (
                    db.session.query(ModelLinkkfProgram)
                    .filter_by(programcode=LogicLinkkf.current_data["code"])
                    .first()
                )
                LogicLinkkf.current_data["season"] = season
                program.season = season
                db.session.commit()
                total_epi = None
                for entity in LogicLinkkf.current_data["episode"]:
                    entity["filename"] = LogicLinkkf.get_filename(
                        LogicLinkkf.current_data["save_folder"],
                        LogicLinkkf.current_data["season"],
                        entity["title"],
                        total_epi,
                    )
                return LogicLinkkf.current_data
            else:
                ret["ret"] = False
                ret["log"] = "No current data!!"
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            ret["ret"] = False
            ret["log"] = str(e)
        return ret

    @staticmethod
    def add_whitelist(*args):
        ret = {}

        logger.debug(f"args: {args}")
        try:

            if len(args) == 0:
                code = str(LogicLinkkf.current_data["code"])
            else:
                # code = str(args[0])
                code = str(args[0]["data_code"])

            whitelist_program = ModelSetting.get("whitelist_program")
            whitelist_programs = [
                str(x.strip().replace(" ", ""))
                for x in whitelist_program.replace("\n", ",").split(",")
            ]
            if code not in whitelist_programs:
                whitelist_programs.append(code)
                whitelist_programs = filter(
                    lambda x: x != "", whitelist_programs
                )  # remove blank code
                whitelist_program = ",".join(whitelist_programs)
                entity = (
                    db.session.query(ModelSetting)
                    .filter_by(key="whitelist_program")
                    .with_for_update()
                    .first()
                )
                entity.value = whitelist_program
                db.session.commit()
                ret["ret"] = True
                ret["code"] = code
                if len(args) == 0:
                    return LogicLinkkf.current_data
                else:
                    return ret
            else:
                ret["ret"] = False
                ret["log"] = "이미 추가되어 있습니다."
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            ret["ret"] = False
            ret["log"] = str(e)
        return ret

    @staticmethod
    async def fetch_url(session, url):
        async with session.get(url) as resp:
            # print(type(resp.text()))
            data = []
            html_content = await resp.text()
            tree = html.fromstring(html_content)
            tmp_items = tree.xpath('//div[@class="myui-vodlist__box"]')
            for item in tmp_items:
                entity = {}
                entity["link"] = item.xpath(".//a/@href")[0]
                entity["code"] = re.search(r"[0-9]+", entity["link"]).group()
                data.append(entity["code"])
            return data

    @staticmethod
    # def flatten_list(nested_list):
    #     flat_list = []
    #     if isinstance(nested_list, list):
    #         for sublist in nested_list:
    #             flat_list.extend(flatten_list(sublist))
    #     else:
    #         flat_list.append(nested_list)
    #     return flat_list
    def flatten_list(nested_list):
        flat_list = []
        for sublist in nested_list:
            for item in sublist:
                flat_list.append(item)
        return flat_list

    @staticmethod
    @linkkf_async_timeit
    async def get_airing_code():
        try:
            data = LogicLinkkf._get_home_response()
            codes = [item["code"] for item in data.get("episode", []) if item.get("code")]
            logger.debug(codes)
            return codes

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_airing_info():
        try:
            return LogicLinkkf._get_home_response()

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_search_result(query):

        try:
            _query = urllib.parse.quote(query)
            url = f"{ModelSetting.get('linkkf_url').rstrip('/')}/view/?wd={_query}"
            logger.debug("search url::> %s", url)
            html_content = LogicLinkkf.get_html(url)
            soup = BeautifulSoup(html_content, "html.parser")
            items = LogicLinkkf._parse_vod_items(soup)
            data = {
                "ret": "success",
                "query": query,
                "total_page": LogicLinkkf._parse_total_page(soup),
                "episode_count": len(items),
                "episode": items,
            }
            return data

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_anime_list_info(cate, page):
        try:
            if cate == "ing":
                return LogicLinkkf._get_list_response("/list/2/", page)
            elif cate == "movie":
                return LogicLinkkf._get_list_response("/list/2/lang/Movie/", page)
            elif cate == "complete":
                return LogicLinkkf._get_list_response("/list/9/", page)
            elif cate == "top_view":
                return LogicLinkkf._get_home_response()
            return {"ret": "success", "page": int(page), "total_page": 0, "episode_count": 0, "episode": []}

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_screen_movie_info(page):
        try:
            return LogicLinkkf._get_list_response("/list/2/lang/Movie/", page)

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_complete_anilist_info(page):
        try:
            return LogicLinkkf._get_list_response("/list/9/", page)

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_title_info(code):
        try:
            if (
                LogicLinkkf.current_data is not None
                and LogicLinkkf.current_data["code"] == code
                and LogicLinkkf.current_data["ret"]
            ):
                return LogicLinkkf.current_data
            url = "%s/%s" % (ModelSetting.get("linkkf_url"), code)
            logger.info(url)

            # logger.debug(f"LogicLinkkf.headers: {LogicLinkkf.headers}")

            html_content = LogicLinkkf.get_html(url, cached=False)
            # html_content = LogicLinkkf.get_html_playwright(url)
            # html_content = LogicLinkkf.get_html_cloudflare(url, cached=False)

            sys.setrecursionlimit(10**7)
            # logger.info(html_content)
            tree = html.fromstring(html_content)
            # tree = etree.fromstring(
            #     html_content, parser=etree.XMLParser(huge_tree=True)
            # )
            # tree1 = BeautifulSoup(html_content, "lxml")

            soup = BeautifulSoup(html_content, "html.parser")
            # tree = etree.HTML(str(soup))
            # logger.info(tree)

            data = {"code": code, "ret": False}
            tmp = soup.select("ul > a")

            # logger.debug(f"tmp1 size:=> {str(len(tmp))}")

            try:
                tmp = (
                    tree.xpath('//div[@class="hrecipe"]/article/center/strong')[
                        0
                    ]
                    .text_content()
                    .strip()
                )
            except IndexError:
                tmp = (
                    tree.xpath("//article/center/strong")[0]
                    .text_content()
                    .strip()
                )
            match = re.compile(r"(?P<season>\d+)기").search(tmp)
            if match:
                data["season"] = match.group("season")
            else:
                data["season"] = "1"

            # replace_str = f'({data["season"]}기)'
            # logger.info(replace_str)
            data["_id"] = str(code)
            data["title"] = tmp.replace(data["season"] + "기", "").strip()
            data["title"] = data["title"].replace("()", "").strip()
            data["title"] = (
                Util.change_text_for_use_filename(data["title"])
                .replace("OVA", "")
                .strip()
            )
            # logger.info(f"title:: {data['title']}")
            try:
                data["poster_url"] = tree.xpath(
                    '//div[@class="myui-content__thumb"]/a/@data-original'
                )
                # print(tree.xpath('//div[@class="myui-content__detail"]/text()'))
                if (
                    len(
                        tree.xpath(
                            '//div[@class="myui-content__detail"]/text()'
                        )
                    )
                    > 3
                ):
                    data["detail"] = [
                        {
                            "info": tree.xpath(
                                '//div[@class="myui-content__detail"]/text()'
                            )[3]
                        }
                    ]
                else:
                    data["detail"] = [{"정보없음": ""}]
            except Exception as e:
                logger.error(e)
                data["detail"] = [{"정보없음": ""}]
                data["poster_url"] = None

            data["rate"] = tree.xpath('span[@class="tag-score"]')
            # tag_score = tree.xpath('//span[@class="taq-score"]').text_content().strip()
            tag_score = tree.xpath('//span[@class="taq-score"]')[
                0
            ].text_content()
            # logger.debug(tag_score)
            tag_count = (
                tree.xpath('//span[contains(@class, "taq-count")]')[0]
                .text_content()
                .strip()
            )
            data_rate = tree.xpath('//div[@class="rating"]/div/@data-rate')
            # logger.debug("data_rate::> %s", data_rate)
            # tmp = tree.xpath('//*[@id="relatedpost"]/ul/li')
            # tmp = tree.xpath('//article/a')
            # 수정된
            # tmp = tree.xpath("//ul/a")
            tmp = soup.select("ul > a")

            # logger.debug(f"tmp size:=> {str(len(tmp))}")
            # logger.info(tmp)
            if tmp is not None:
                data["episode_count"] = str(len(tmp))
            else:
                data["episode_count"] = "0"

            data["episode"] = []
            # tags = tree.xpath(
            #     '//*[@id="syno-nsc-ext-gen3"]/article/div[1]/article/a')
            # tags = tree.xpath("//ul/a")
            tags = soup.select("ul > u > a")
            if len(tags) > 0:
                pass
            else:
                tags = soup.select("ul > a")
            total_epi_no = len(tags)
            logger.debug(len(tags))

            # logger.info("tags", tags)
            # re1 = re.compile(r'\/(?P<code>\d+)')
            re1 = re.compile(r"\-([^-])+\.")

            data["save_folder"] = data["title"]
            # logger.debug(f"save_folder::> {data['save_folder']}")

            program = (
                db.session.query(ModelLinkkfProgram)
                .filter_by(programcode=code)
                .first()
            )

            if program is None:
                program = ModelLinkkfProgram(data)
                db.session.add(program)
                db.session.commit()
            else:
                data["save_folder"] = program.save_folder
                data["season"] = program.season

            idx = 1
            for t in tags:
                entity = {
                    "_id": data["code"],
                    "program_code": data["code"],
                    "program_title": data["title"],
                    "save_folder": Util.change_text_for_use_filename(
                        data["save_folder"]
                    ),
                    "title": t.text.strip(),
                    # "title": t.text_content().strip(),
                }
                # entity['code'] = re1.search(t.attrib['href']).group('code')

                # logger.debug(f"title ::>{entity['title']}")

                # 고유id임을 알수 없는 말도 안됨..
                # 에피소드 코드가 고유해야 상태값 갱신이 제대로 된 값에 넣어짐
                p = re.compile(r"([0-9.]+)화?")
                try:
                    m_obj = p.match(entity["title"])
                except:
                    m_obj = None
                logger.debug(entity["title"])
                # entity['code'] = data['code'] + '_' +str(idx)

                episode_code = None
                try:
                    logger.debug(
                        f"m_obj::> {m_obj.group(0)} {data['title']} {entity['title']}"
                    )
                    logger.debug(
                        f"m_obj::> {m_obj.group(1)} {data['title']} {entity['title']}"
                    )
                except:
                    pass
                if m_obj is not None:
                    episode_code = m_obj.group(1)
                    entity["code"] = data["code"] + episode_code.zfill(4)
                else:
                    entity["code"] = data["code"]

                logger.debug("episode_code", entity["code"])
                # entity["url"] = t.attrib["href"]
                check_url = t["href"]
                if check_url.startswith("http"):
                    entity["url"] = t["href"]
                else:
                    entity["url"] = (
                        f"{ModelSetting.get('linkkf_url')}{t['href']}"
                    )
                entity["season"] = data["season"]

                # 저장경로 저장
                tmp_save_path = ModelSetting.get("download_path")
                if ModelSetting.get("auto_make_folder") == "True":
                    program_path = os.path.join(
                        tmp_save_path, entity["save_folder"]
                    )
                    entity["save_path"] = program_path
                    if ModelSetting.get("linkkf_auto_make_season_folder") == "True":
                        entity["save_path"] = os.path.join(
                            entity["save_path"],
                            "Season %s" % int(entity["season"]),
                        )

                data["episode"].append(entity)
                entity["image"] = data["poster_url"]

                # entity['title'] = t.text_content().strip().encode('utf8')

                # entity['season'] = data['season']
                # logger.debug(f"save_folder::2> {data['save_folder']}")
                entity["filename"] = LogicLinkkf.get_filename(
                    data["save_folder"],
                    data["season"],
                    entity["title"],
                    total_epi_no,
                )
                idx = idx + 1
                total_epi_no -= 1
            data["ret"] = True
            # logger.info('data', data)
            LogicLinkkf.current_data = data

            # srt 파일 처리

            return data
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            data["log"] = str(e)
            data["ret"] = "error"
            return data
        except IndexError as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            data["log"] = str(e)
            data["ret"] = "error"
            return data

    @staticmethod
    def get_title_info(code):
        try:
            code = LogicLinkkf._normalize_code(code)
            if (
                LogicLinkkf.current_data is not None
                and LogicLinkkf.current_data["code"] == code
                and LogicLinkkf.current_data["ret"]
            ):
                return LogicLinkkf.current_data

            url = f"{ModelSetting.get('linkkf_url').rstrip('/')}/ani/{code}/"
            logger.info(url)
            html_content = LogicLinkkf.get_html(url, cached=False)
            soup = BeautifulSoup(html_content, "html.parser")

            data = {"code": code, "_id": str(code), "ret": False}

            title_node = soup.select_one(".detail-info-title") or soup.select_one("title")
            raw_title = title_node.get_text(" ", strip=True) if title_node is not None else code
            data["title"], data["season"] = LogicLinkkf._parse_program_title(raw_title)

            poster_node = soup.select_one("img[data-original]")
            data["poster_url"] = (
                poster_node.get("data-original", "").strip() if poster_node is not None else None
            )
            data["detail"] = LogicLinkkf._parse_detail_rows(soup)

            tags = soup.select(".episode-box a[href^='/watch/']")
            if len(tags) == 0:
                tags = soup.select("a.text-overflow.ep[href^='/watch/']")

            data["episode_count"] = str(len(tags))
            data["episode"] = []
            data["save_folder"] = data["title"]

            program = (
                db.session.query(ModelLinkkfProgram)
                .filter_by(programcode=code)
                .first()
            )

            if program is None:
                program = ModelLinkkfProgram(data)
                db.session.add(program)
                db.session.commit()
            else:
                data["save_folder"] = program.save_folder
                data["season"] = program.season

            total_epi_no = len(tags)
            for idx, tag in enumerate(tags, start=1):
                episode_title = tag.get_text(" ", strip=True).strip()
                href = tag.get("href", "").strip()
                if href == "":
                    continue

                entity = {
                    "_id": data["code"],
                    "program_code": data["code"],
                    "program_title": data["title"],
                    "save_folder": Util.change_text_for_use_filename(data["save_folder"]),
                    "title": episode_title,
                }

                match = re.search(r"([0-9]+(?:\.[0-9]+)?)", episode_title)
                if match is not None:
                    episode_code = match.group(1).replace(".", "")
                    entity["code"] = data["code"] + episode_code.zfill(4)
                else:
                    entity["code"] = f"{data['code']}_{idx:04d}"

                if href.startswith("http"):
                    entity["url"] = href
                else:
                    entity["url"] = urllib.parse.urljoin(ModelSetting.get("linkkf_url"), href)
                entity["season"] = data["season"]

                tmp_save_path = ModelSetting.get("download_path")
                if ModelSetting.get("auto_make_folder") == "True":
                    program_path = os.path.join(tmp_save_path, entity["save_folder"])
                    entity["save_path"] = program_path
                    if ModelSetting.get("linkkf_auto_make_season_folder") == "True":
                        entity["save_path"] = os.path.join(
                            entity["save_path"],
                            "Season %s" % int(entity["season"]),
                        )

                entity["image"] = data["poster_url"]
                entity["filename"] = LogicLinkkf.get_filename(
                    data["save_folder"],
                    data["season"],
                    entity["title"],
                    total_epi_no,
                )
                data["episode"].append(entity)
                total_epi_no -= 1

            logger.debug("request analysis parsed episodes: %s", len(data["episode"]))
            data["ret"] = True
            LogicLinkkf.current_data = data
            return data
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())
            data = {"code": str(code), "ret": "error", "log": str(e)}
            return data

    @staticmethod
    def get_filename(maintitle, season, title, total_epi):
        try:
            logger.debug(
                "get_filename()= %s %s %s %s",
                maintitle,
                season,
                title,
                total_epi,
            )
            match = re.compile(
                r"(?P<title>.*?)\s?((?P<season>\d+)기)?\s?((?P<epi_no>\d+)화?)"
            ).search(title)
            if match:
                # epi_no_ckeck = match.group("epi_no")
                # logger.debug('EP 문자 %s', epi_no_ckeck)
                # if ' ' in title:
                #    tes = title.find(' ')
                #    epi_no = int(title[0:tes])
                #    title = epi_no
                #    logger.debug('EP 포함 문자(공백) %s', epi_no)
                # elif 'OVA' in title:
                #    tes = title.find('OVA')
                #    check = int(tes)
                #    if check == 0:
                #        epi_no = total_epi
                #    else:
                #        epi_no = int(title[0:tes])
                #    title = epi_no
                #    logger.debug('EP 포함 문자(OVA) %s', epi_no)
                # elif 'SP' in title:
                #    tes = title.find('SP')
                #    epi_no = int(title[0:tes])
                #    title = epi_no
                #    logger.debug('EP 포함 문자 (SP) %s', epi_no)
                # elif '-' in title:
                #    tes = title.find('-')
                #    epi_no = int(title[0:tes])
                #    title = epi_no
                #    logger.debug('EP 포함 문자(-) %s', epi_no)
                # else:
                #    epi_no = int(match.group("epi_no"))
                #    logger.debug('EP 문자 %s', epi_no)
                # try:
                #    logger.debug("epi_no: %s %s", int(epi_no), int(title))
                #    if epi_no == int(title):
                #        if epi_no < 10:
                #            epi_no = "0%s" % epi_no
                #        else:
                #            epi_no = "%s" % epi_no
                # except:
                #    logger.debug("epi_no: %s %s", int(epi_no), float(title))
                #    if epi_no < 10:
                #        epi_no = '0%.1f'%float(title)
                #    epi_no = "0%s-pt1" % epi_no
                #    else:
                #        epi_no = '%.1f'%float(title)
                #    epi_no = "%s-pt1" % epi_no
                epi_no = total_epi
                if epi_no < 10:
                    epi_no = "0%s" % epi_no
                else:
                    epi_no = "%s" % epi_no

                if int(season) < 10:
                    season = "0%s" % season
                else:
                    season = "%s" % season

                # title_part = match.group('title').strip()
                # ret = '%s.S%sE%s%s.720p-SA.mp4' % (maintitle, season, epi_no, date_str)
                ret = "%s.S%sE%s.720p-LK.mp4" % (maintitle, season, epi_no)
            else:
                logger.debug("NOT MATCH")
                ret = "%s.720p-LK.mp4" % maintitle

            return Util.change_text_for_use_filename(ret)
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def _extract_player_payload(html_text):
        marker = "var player_aaaa="
        start = html_text.find(marker)
        if start < 0:
            return None

        start = html_text.find("{", start)
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        quote = None
        end = None

        for idx in range(start, len(html_text)):
            char = html_text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    in_string = False
            else:
                if char in ['"', "'"]:
                    in_string = True
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break

        if end is None:
            return None

        payload_text = html_text[start:end]
        try:
            return json.loads(payload_text)
        except Exception:
            try:
                return json.loads(payload_text.replace("\\/", "/"))
            except Exception as e:
                logger.error("Exception:%s", e)
                logger.error(traceback.format_exc())
                return None

    @staticmethod
    def _extract_stream_config(player_html, base_url):
        video_url = None
        vtt_url = None

        video_match = re.search(r'videoUrl\s*:\s*["\']([^"\']+)["\']', player_html)
        if video_match is None:
            video_match = re.search(
                r'new\s+Artplayer\(\s*\{.*?\burl\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                player_html,
                re.S,
            )
        if video_match is None:
            video_match = re.search(
                r'\burl\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                player_html,
                re.S,
            )
        if video_match is not None:
            video_url = urllib.parse.urljoin(base_url, video_match.group(1))

        vtt_match = re.search(r'"file"\s*:\s*"([^"]+\.vtt[^"]*)"', player_html)
        if vtt_match is None:
            vtt_match = re.search(
                r'subtitle\s*:\s*\{.*?url\s*:\s*["\']([^"\']+\.vtt[^"\']*)["\']',
                player_html,
                re.S,
            )
        if vtt_match is not None:
            vtt_url = urllib.parse.urljoin(base_url, vtt_match.group(1))

        return video_url, vtt_url

    @staticmethod
    def _get_player_candidates(payload):
        candidates = []

        actual_url = str(payload.get("actual_url", "")).replace("\\/", "/").strip()
        if actual_url != "":
            candidates.append(actual_url)

        stream_code = str(payload.get("url", "")).replace("\\/", "/").strip()
        play_from = str(payload.get("from", "")).strip().lower()

        if (
            stream_code != ""
            and stream_code.startswith("http") is False
            and re.match(r"^[A-Za-z0-9._-]+$", stream_code) is not None
            and play_from in ["sub", "dub", ""]
        ):
            for target in [
                f"https://play.sub3.top/r2/play.php?&id=pp2&url={stream_code}",
                f"https://playv2.sub3.top/r2/playhd2.php?&id=n21&url={stream_code}",
            ]:
                if target not in candidates:
                    candidates.append(target)

        return candidates

    @staticmethod
    def get_video_url(episode_url: str) -> list:
        try:
            if episode_url.startswith("http"):
                url = episode_url
            else:
                url = urllib.parse.urljoin(ModelSetting.get("linkkf_url"), episode_url)

            logger.info("get_video_url(): url: %s", url)

            if "playhd2.php" in url or "play.php" in url:
                player_html = LogicLinkkf.get_html(url)
                video_url, vtt_url = LogicLinkkf._extract_stream_config(player_html, url)
                if video_url is not None:
                    return [video_url, url, vtt_url]

            html_text = LogicLinkkf.get_html(url)
            payload = LogicLinkkf._extract_player_payload(html_text)

            if payload is not None:
                for target in LogicLinkkf._get_player_candidates(payload):
                    player_html = LogicLinkkf.get_html(target)
                    video_url, vtt_url = LogicLinkkf._extract_stream_config(player_html, target)
                    if video_url is not None:
                        return [video_url, target, vtt_url]

                server_urls = re.findall(r'data-url=["\']([^"\']+)["\']', html_text)
                for server_url in server_urls:
                    target = server_url.replace("&amp;", "&")
                    if target.startswith("/"):
                        target = urllib.parse.urljoin(url, target)
                    player_html = LogicLinkkf.get_html(target)
                    video_url, vtt_url = LogicLinkkf._extract_stream_config(player_html, target)
                    if video_url is not None:
                        return [video_url, target, vtt_url]

            pattern = re.compile(r"player_post\('https:\/\/.*?'\)").findall(html_text)
            fallback_urls = []
            for tag in pattern:
                target = tag[13:-2]
                if "ds" in target or "hls" in target or "subkf" in target:
                    continue
                if target not in fallback_urls:
                    fallback_urls.append(target)

            for target in fallback_urls:
                result = LogicLinkkf.get_video_url_from_url(url, target)
                if result[0] is not None:
                    return result

        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

        return [None, None, None]

    @staticmethod
    def download_subtitle(info):
        # logger.debug(info)
        ani_url = LogicLinkkf.get_video_url(info["url"])
        # logger.debug(f"ani_url: {ani_url}")

        referer = None

        # vtt file to srt file
        from urllib import parse

        if ani_url[1] is not None:
            referer = ani_url[1]
        else:
            referer = ModelSetting.get("linkkf_url")

        logger.debug(f"referer:: {referer}")

        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/71.0.3554.0 Safari/537.36Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3554.0 Safari/537.36",
            "Referer": f"{referer}",
        }
        logger.debug(headers)

        save_path = ModelSetting.get("download_path")
        if ModelSetting.get("auto_make_folder") == "True":
            program_path = os.path.join(save_path, info["save_folder"])
            save_path = program_path
            if ModelSetting.get("linkkf_auto_make_season_folder") == "True":
                save_path = os.path.join(
                    save_path, "Season %s" % int(info["season"])
                )

        ret = re.compile(r"(http(s)?:\/\/)([a-z0-9\w]+\.*)+[a-z0-9]{2,4}")
        base_url_vtt = ret.match(referer)

        if ani_url[2] is None:
            return
        if ani_url[2].startswith("http"):
            vtt_url = ani_url[2]
        else:
            vtt_url = base_url_vtt[0] + ani_url[2]

        logger.debug(f"srt:url => {vtt_url}")
        srt_filepath = os.path.join(
            save_path, info["filename"].replace(".mp4", ".ko.srt")
        )
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        # logger.info('srt_filepath::: %s', srt_filepath)
        if ani_url[2] is not None and not os.path.exists(srt_filepath):
            res = requests.get(vtt_url, headers=headers)
            vtt_data = res.text
            vtt_status = res.status_code
            if vtt_status == 200:
                srt_data = convert_vtt_to_srt(vtt_data)
                write_file(srt_data, srt_filepath)
            else:
                logger.debug("자막파일 받을수 없슴")

    @staticmethod
    def chunks(l, n):
        n = max(1, n)
        return (l[i : i + n] for i in range(0, len(l), n))

    @staticmethod
    def get_info_by_code(code):
        logger.debug("get_info_by_code: %s", code)

        try:
            if LogicLinkkf.current_data is not None:
                for t in LogicLinkkf.current_data["episode"]:
                    if t["code"] == code:
                        logger.debug(t["code"])
                        return t
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            logger.debug("Linkkf scheduler_function start..")

            whitelist_program = ModelSetting.get("whitelist_program")
            whitelist_programs = [
                x.strip().replace(" ", "")
                for x in whitelist_program.replace("\n", ",").split(",")
            ]

            logger.debug(f"whitelist_programs: {whitelist_programs}")

            for code in whitelist_programs:
                logger.info("auto download start : %s", code)
                downloaded = (
                    db.session.query(ModelLinkkf)
                    .filter(ModelLinkkf.completed.is_(True))
                    .filter_by(programcode=code)
                    .with_for_update()
                    .all()
                )
                logger.debug(f"downloaded:: {downloaded}")
                dl_codes = [dl.episodecode for dl in downloaded]
                # logger.debug("dl_codes:: %s", dl_codes)
                logger.info("downloaded codes :%s", dl_codes)

                # if len(dl_codes) > 0:
                data = LogicLinkkf.get_title_info(code)
                logger.debug(f"data:: {data}")

                for episode in data["episode"]:
                    e_code = episode["code"]
                    if e_code not in dl_codes:
                        logger.info("Logic Queue added :%s", e_code)

                        logger.debug(f"episode:: {episode}")
                        print("temp==============")
                        LogicQueue.add_queue(episode)

            logger.debug("========================================")
        except Exception as e:
            logger.error("Exception:%s", e)
            logger.error(traceback.format_exc())

    @staticmethod
    def reset_db() -> bool:
        db.session.query(ModelLinkkf).delete()
        db.session.commit()
        return True
