(function () {
  if (window.__linkkfRequestInitialized === true) {
    return;
  }
  window.__linkkfRequestInitialized = true;

  let currentData = null;
  let currentAiringData = null;
  let code = "";
  let analysisInProgress = false;

  const normalizeCode = (value) => {
    const raw = String(value || "").trim();
    if (raw === "") {
      return "";
    }
    const match = raw.match(/\/(?:ani|watch)\/(\d+)\//) || raw.match(/(\d{3,})/);
    return match ? match[1] : raw;
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const mButton = (id, text, attrs = [], extraClass = "btn-primary") => {
    const extraAttrs = (attrs || [])
      .map((item) => ` data-${item.key}="${escapeHtml(item.value)}"`)
      .join("");
    return `<button type="button" id="${escapeHtml(id)}" class="btn btn-sm ${extraClass} mr-1 mb-1"${extraAttrs}>${escapeHtml(text)}</button>`;
  };

  const mButtonGroup = (inner) =>
    `<div class="d-flex flex-wrap align-items-center mb-3">${inner}</div>`;

  const mHrBlack = () => '<hr class="my-3" style="border-color: rgba(255,255,255,0.25);">';
  const mHr = () => '<hr class="my-2" style="border-color: rgba(255,255,255,0.15);">';
  const mRowStart = () => '<div class="row">';
  const mRowEnd = () => "</div>";
  const mCol = (size, content, align) => {
    const alignClass = align === "right" ? " text-right" : "";
    return `<div class="col-md-${size}${alignClass}">${content ?? ""}</div>`;
  };

  function notifyWarning(message) {
    $.notify(`<strong>${message}</strong>`, { type: "warning" });
  }

  function notifySuccess(message) {
    $.notify(`<strong>${message}</strong>`, { type: "success" });
  }

  function setAnalysisLoading(flag) {
    analysisInProgress = flag === true;
    const analysisButton = document.getElementById("analysis_btn");
    if (analysisButton) {
      analysisButton.disabled = analysisInProgress;
    }
  }

  function openPlayerPage(url) {
    if (!url) {
      notifyWarning("재생 URL을 가져오지 못했습니다.");
      return;
    }
    window.open(url, "_blank");
  }

  function requestPlay(payload) {
    $.ajax({
      url: `/${package_name}/ajax/play`,
      type: "POST",
      cache: false,
      data: payload,
      dataType: "json",
      success: function (ret) {
        if (ret.ret === "success" && ret.data != null) {
          openPlayerPage(ret.data.play_url);
        } else {
          notifyWarning(ret.log || "재생 정보를 가져오지 못했습니다.");
        }
      },
      error: function () {
        notifyWarning("재생 정보를 가져오지 못했습니다.");
      },
    });
  }

  function getAiringList() {
    $.ajax({
      url: `/${package_name}/ajax/airing_list`,
      type: "GET",
      cache: false,
      dataType: "json",
      success: (ret) => {
        if (ret.ret === "success" && Array.isArray(ret.episode)) {
          currentAiringData = ret;
          makeAiringList(ret);
        } else {
          notifyWarning(ret.log || "최신 목록을 불러오지 못했습니다.");
        }
      },
      error: function () {
        notifyWarning("최신 목록을 불러오지 못했습니다.");
      },
    });
  }

  function makeAiringList(data) {
    let str = "";
    str += mHrBlack();
    str += '<div id="inner_airing" class="d-flex flex-wrap">';
    for (const item of data.episode) {
      str += `
        <div class="mx-1 mb-1">
          <button
            type="button"
            class="btn btn-primary code-button"
            data-code="${escapeHtml(item.code)}"
            title="${escapeHtml(item.title)}"
          >
            ${escapeHtml(item.code)}
          </button>
        </div>
      `;
    }
    str += "</div>";
    str += mHrBlack();
    document.getElementById("airing_list").innerHTML = str;
  }

  function renderProgram(data) {
    currentData = data;

    let str = "";
    let tmp = '<div class="form-inline w-100">';
    tmp += mButton("check_download_btn", "선택 다운로드 추가");
    tmp += mButton("all_check_on_btn", "전체 선택");
    tmp += mButton("all_check_off_btn", "전체 해제");
    tmp += mButton("down_subtitle_btn", "자막 전체 받기");
    tmp += `&nbsp;&nbsp;&nbsp;<input id="new_title" name="new_title" class="form-control form-control-sm" value="${escapeHtml(data.title)}">`;
    tmp += "</div>";
    tmp += '<div class="form-inline">';
    tmp += mButton("apply_new_title_btn", "폴더명 변경");
    tmp += `&nbsp;&nbsp;&nbsp;<input id="new_season" name="new_season" class="form-control form-control-sm" value="${escapeHtml(data.season)}">`;
    tmp += mButton("apply_new_season_btn", "시즌 변경");
    tmp += mButton("search_tvdb_btn", "TVDB", [], "btn-outline-info");
    tmp += mButton("add_whitelist", "자동 다운로드 추가", [], "btn-outline-success");
    tmp += "</div>";
    str += mButtonGroup(tmp);

    str += "<div class='card p-lg-5 mt-md-3 p-md-3 border-light'>";
    str += mRowStart();
    str += mCol(3, data.poster_url ? `<img src="${escapeHtml(data.poster_url)}" class="img-fluid">` : "");

    let detailHtml = "";
    detailHtml += mRowStart();
    detailHtml += mCol(3, "제목", "right");
    detailHtml += mCol(9, escapeHtml(data.title));
    detailHtml += mRowEnd();
    detailHtml += mRowStart();
    detailHtml += mCol(3, "시즌", "right");
    detailHtml += mCol(9, escapeHtml(data.season));
    detailHtml += mRowEnd();
    for (const detailRow of data.detail || []) {
      const key = Object.keys(detailRow)[0];
      const value = detailRow[key];
      detailHtml += mRowStart();
      detailHtml += mCol(3, escapeHtml(key), "right");
      detailHtml += mCol(9, escapeHtml(value));
      detailHtml += mRowEnd();
    }
    str += mCol(9, detailHtml);
    str += mRowEnd();
    str += "</div>";

    for (let i = 0; i < (data.episode || []).length; i += 1) {
      const episode = data.episode[i];
      str += mRowStart();

      tmp = `<strong>${escapeHtml(episode.title)}</strong><br>`;
      tmp += `${escapeHtml(episode.filename)}<br><p></p>`;
      tmp += '<div class="form-inline">';
      tmp += `
        <input
          id="checkbox_${escapeHtml(episode.code)}"
          name="checkbox_${escapeHtml(episode.code)}"
          type="checkbox"
          checked
          data-toggle="toggle"
          data-on="선택"
          data-off="-"
          data-onstyle="success"
          data-offstyle="danger"
          data-size="small"
        >&nbsp;&nbsp;&nbsp;&nbsp;
      `;
      tmp += mButton("add_queue_btn", "다운로드 추가", [{ key: "idx", value: i }]);
      tmp += mButton("play_video_btn", "보기", [{ key: "idx", value: i }], "btn-outline-info");
      tmp += "</div>";

      str += mCol(12, tmp);
      str += mRowEnd();
      if (i !== data.episode.length - 1) {
        str += mHr();
      }
    }

    document.getElementById("episode_list").innerHTML = str;
    $('input[id^="checkbox_"]').bootstrapToggle();
  }

  $("body").on("click", "button.code-button", function (e) {
    e.preventDefault();
    document.getElementById("code").value = $(this).data("code");
    $("#airing_list").toggle();
    runAnalysis();
  });

  function runAnalysis() {
    if (analysisInProgress) {
      return;
    }
    const input = document.getElementById("code");
    code = normalizeCode(input.value);
    input.value = code;

    if (code === "") {
      notifyWarning("code 값을 입력해 주세요.");
      return;
    }

    setAnalysisLoading(true);

    $.ajax({
      url: `/${package_name}/ajax/analysis`,
      type: "POST",
      cache: false,
      data: { code },
      dataType: "json",
      success: function (ret) {
        if (ret.ret === "success" && ret.data != null) {
          renderProgram(ret.data);
        } else {
          notifyWarning(ret.log || "분석에 실패했습니다.");
        }
      },
      error: function () {
        notifyWarning("분석 요청에 실패했습니다.");
      },
      complete: function () {
        setAnalysisLoading(false);
      },
    });
  }

  $("body").on("click", "#analysis_btn", function (e) {
    e.preventDefault();
    runAnalysis();
  });

  $("body").on("click", "#go_linkkf_btn", function (e) {
    e.preventDefault();
    window.open(linkkf_url, "_blank");
  });

  $("body").on("click", "#all_check_on_btn", function (e) {
    e.preventDefault();
    $('input[id^="checkbox_"]').bootstrapToggle("on");
  });

  $("body").on("click", "#all_check_off_btn", function (e) {
    e.preventDefault();
    $('input[id^="checkbox_"]').bootstrapToggle("off");
  });

  $("body").on("click", "#search_tvdb_btn", function (e) {
    e.preventDefault();
    const newTitle = document.getElementById("new_title").value;
    window.open(`https://www.thetvdb.com/search?query=${encodeURIComponent(newTitle)}`, "_blank");
  });

  $("body").on("click", "#add_whitelist", function (e) {
    e.preventDefault();
    $.ajax({
      url: `/${package_name}/ajax/add_whitelist`,
      type: "POST",
      cache: false,
      data: { code: currentData?.code || code || "" },
      dataType: "json",
      success: function (ret) {
        if (ret.ret) {
          notifySuccess("추가되었습니다.");
        } else {
          notifyWarning(ret.log || "추가에 실패했습니다.");
        }
      },
      error: function () {
        notifyWarning("추가에 실패했습니다.");
      },
    });
  });

  $("body").on("click", "#down_subtitle_btn", function (e) {
    e.preventDefault();

    const all = $('input[id^="checkbox_"]');
    let str = "";
    for (let i = 0; i < all.length; i += 1) {
      if (all[i].checked) {
        str += `${all[i].id.split("_")[1]},`;
      }
    }
    if (str === "") {
      notifyWarning("선택해 주세요.");
      return;
    }

    $.ajax({
      url: `/${package_name}/ajax/down_subtitle_list`,
      type: "POST",
      cache: false,
      data: { code: str },
      dataType: "json",
      success: function (ret) {
        if (ret.ret === "success") {
          notifySuccess(`${ret.log}개를 처리했습니다.`);
        } else {
          notifyWarning(ret.log || "자막 다운로드에 실패했습니다.");
        }
      },
    });
  });

  $("body").on("click", "#apply_new_title_btn", function (e) {
    e.preventDefault();
    const newTitle = document.getElementById("new_title").value;
    $.ajax({
      url: `/${package_name}/ajax/apply_new_title`,
      type: "POST",
      cache: false,
      data: { new_title: newTitle },
      dataType: "json",
      success: function (ret) {
        if (ret.ret) {
          notifySuccess("적용되었습니다.");
          renderProgram(ret);
        } else {
          notifyWarning(ret.log || "적용에 실패했습니다.");
        }
      },
    });
  });

  $("body").on("click", "#apply_new_season_btn", function (e) {
    e.preventDefault();
    const newSeason = document.getElementById("new_season").value;
    if ($.isNumeric(newSeason) === false) {
      notifyWarning("시즌은 숫자여야 합니다.");
      return;
    }
    $.ajax({
      url: `/${package_name}/ajax/apply_new_season`,
      type: "POST",
      cache: false,
      data: { new_season: newSeason },
      dataType: "json",
      success: function (ret) {
        if (ret.ret) {
          notifySuccess("적용되었습니다.");
          renderProgram(ret);
        } else {
          notifyWarning(ret.log || "적용에 실패했습니다.");
        }
      },
    });
  });

  $("body").on("click", "#add_queue_btn", function (e) {
    e.preventDefault();
    const idx = Number($(this).data("idx"));
    const episode = currentData?.episode?.[idx];
    if (episode == null) {
      notifyWarning("에피소드 정보를 찾지 못했습니다.");
      return;
    }

    $.ajax({
      url: `/${package_name}/ajax/add_queue`,
      type: "POST",
      cache: false,
      data: { code: episode.code, data: JSON.stringify(episode) },
      dataType: "json",
      success: function (ret) {
        if (ret.ret === "enqueue_db_append") {
          notifySuccess("다운로드 작업에 추가했습니다.");
        } else if (ret.ret === "enqueue_db_exist") {
          notifyWarning("이미 DB에 있는 항목입니다.");
        } else if (ret.ret === "db_completed") {
          notifyWarning("이미 완료 기록이 있습니다.");
        } else if (ret.ret === "queue_exist") {
          notifyWarning("이미 대기열에 있습니다.");
        } else if (ret.ret === "no_data") {
          notifyWarning("에피소드 정보를 찾지 못했습니다.");
        } else {
          notifyWarning(ret.log || "대기열 추가에 실패했습니다.");
        }
      },
    });
  });

  $("body").on("click", "#play_video_btn", function (e) {
    e.preventDefault();
    const idx = Number($(this).data("idx"));
    const episode = currentData?.episode?.[idx];
    if (episode == null) {
      notifyWarning("에피소드 정보를 찾지 못했습니다.");
      return;
    }
    requestPlay({
      url: episode.url,
      title: `${currentData.title} - ${episode.title}`,
    });
  });

  $("body").on("click", "#check_download_btn", function (e) {
    e.preventDefault();
    const all = $('input[id^="checkbox_"]');
    let str = "";
    for (let i = 0; i < all.length; i += 1) {
      if (all[i].checked) {
        str += `${all[i].id.split("_")[1]},`;
      }
    }
    if (str === "") {
      notifyWarning("선택해 주세요.");
      return;
    }

    $.ajax({
      url: `/${package_name}/ajax/add_queue_checked_list`,
      type: "POST",
      cache: false,
      data: { code: str },
      dataType: "json",
      success: function (ret) {
        if (ret.ret === "success") {
          notifySuccess(`${ret.log}개를 추가했습니다.`);
        } else {
          notifyWarning(ret.log || "대기열 추가에 실패했습니다.");
        }
      },
    });
  });

  $("#go_modal_airing").click(function (e) {
    e.preventDefault();
    if (currentAiringData === null) {
      getAiringList();
    } else {
      $("#airing_list").toggle();
    }
  });

  $("#go_modal_airing").attr("class", "btn btn-primary");

  $(function () {
    const input = document.getElementById("code");
    const autoCode = normalizeCode(input?.value || "");
    if (input && autoCode !== "") {
      input.value = autoCode;
      setTimeout(() => {
        runAnalysis();
      }, 0);
    }
  });
})();
