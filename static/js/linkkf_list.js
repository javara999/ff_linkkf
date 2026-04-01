(function () {
if (window.__linkkfListInitialized === true) {
  return;
}
window.__linkkfListInitialized = true;

let currentData = null;

const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

function getFormData() {
  return $("#form_search").serialize();
}

function normalizeObject(value) {
  if (value && typeof value === "object") {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    try {
      return JSON.parse(value);
    } catch (e) {
      return {};
    }
  }
  return {};
}

function openJsonModal(item) {
  $("#modal_title").text("JSON");
  $("#modal_body").html(`<pre style="white-space: pre-wrap; word-break: break-all;">${escapeHtml(JSON.stringify(item, null, 2))}</pre>`);
  $("#large_modal").modal("show");
}

function makeActionButton(id, label, attrs = {}, klass = "btn btn-sm btn-primary mr-1 mb-1") {
  const extra = Object.entries(attrs)
    .map(([key, value]) => ` data-${key}="${escapeHtml(value)}"`)
    .join("");
  return `<button id="${escapeHtml(id)}" class="${klass}"${extra}>${escapeHtml(label)}</button>`;
}

function getStatusLabel(item) {
  if (item.status === "completed") {
    return "완료";
  }
  if (item.status === "error") {
    return "실패";
  }
  if (item.status === "canceled") {
    return "취소";
  }
  if (item.status === "downloading") {
    return "진행중";
  }
  return "대기";
}

function renderPagination(paging) {
  if (!paging) {
    $("#page1").html("");
    $("#page2").html("");
    return;
  }

  let html = `
    <div class="row mb-3">
      <div class="col-sm-12">
        <div class="btn-toolbar justify-content-center" role="toolbar">
          <div class="btn-group btn-group-sm mr-2" role="group">
  `;

  if (paging.prev_page) {
    html += `<button id="page" data-page="${paging.start_page - 1}" type="button" class="btn btn-secondary">&laquo;</button>`;
  }

  for (let i = paging.start_page; i <= paging.last_page; i++) {
    const disabled = i === paging.current_page ? " disabled" : "";
    html += `<button id="page" data-page="${i}" type="button" class="btn btn-secondary"${disabled}>${i}</button>`;
  }

  if (paging.next_page) {
    html += `<button id="page" data-page="${paging.last_page + 1}" type="button" class="btn btn-secondary">&raquo;</button>`;
  }

  html += `
          </div>
        </div>
      </div>
    </div>
  `;

  $("#page1").html(html);
  $("#page2").html(html);
}

function renderList(list) {
  if (!Array.isArray(list) || list.length === 0) {
    $("#list_div").html('<div class="alert alert-secondary">목록이 없습니다.</div>');
    return;
  }

  let html = "";
  for (const item of list) {
    const statusLabel = getStatusLabel(item);
    const contents = normalizeObject(item.contents_json || item.linkkf_info);
    const savePath = item.save_path || contents.save_path || "";
    const filename = item.filename || contents.filename || "";
    const programCode = item.programcode || contents.program_code || "";
    const programTitle = contents.program_title || contents.save_folder || contents.title || filename;
    const completedTime = item.completed_time ? `<div>${escapeHtml(item.completed_time)} (${escapeHtml(statusLabel)})</div>` : "";

    let actions = "";
    actions += makeActionButton("json_btn", "JSON", { id: item.id }, "btn btn-sm btn-info mr-1 mb-1");
    actions += makeActionButton("request_btn", "작품 검색", { content_code: programCode }, "btn btn-sm btn-primary mr-1 mb-1");
    actions += makeActionButton("self_search_btn", "목록 검색", { title: programTitle }, "btn btn-sm btn-secondary mr-1 mb-1");
    actions += makeActionButton("remove_btn", "삭제", { id: item.id }, "btn btn-sm btn-danger mr-1 mb-1");

    html += `
      <div class="card mb-3">
        <div class="card-body">
          <div class="row">
            <div class="col-md-1"><strong>${escapeHtml(item.id)}</strong></div>
            <div class="col-md-2">${escapeHtml(statusLabel)}</div>
            <div class="col-md-3">
              <div>${escapeHtml(item.created_time)} (추가)</div>
              ${completedTime}
            </div>
            <div class="col-md-6">
              <div>${escapeHtml(savePath)}</div>
              <div>${escapeHtml(filename)}</div>
              <div class="mt-2">${actions}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  $("#list_div").html(html);
}

function loadList(page, moveTop = true) {
  let formData = getFormData();
  formData += "&page=" + page;
  $.ajax({
    url: "/" + package_name + "/ajax/web_list",
    type: "POST",
    cache: false,
    data: formData,
    dataType: "json",
    success: (data) => {
      currentData = data;
      if (data && !data.ret) {
        if (moveTop) {
          window.scrollTo(0, 0);
        }
        renderList(data.list);
        renderPagination(data.paging);
      } else {
        $.notify("<strong>목록을 불러오지 못했습니다.</strong>", {
          type: "warning",
        });
      }
    },
    error: () => {
      $.notify("<strong>목록 요청 중 오류가 발생했습니다.</strong>", {
        type: "warning",
      });
    },
  });
}

$(document).ready(function () {
  loadList(1);
});

$("#search").click(function (e) {
  e.preventDefault();
  loadList(1);
});

$("#reset_btn").click(function (e) {
  e.preventDefault();
  document.getElementById("form_search").reset();
  loadList(1);
});

$("body").on("click", "#page", function (e) {
  e.preventDefault();
  loadList($(this).data("page"));
});

$("body").on("click", "#remove_btn", function (e) {
  e.preventDefault();
  const id = $(this).data("id");
  $.ajax({
    url: "/" + package_name + "/ajax/db_remove",
    type: "POST",
    cache: false,
    data: { id },
    dataType: "json",
    success: function (ret) {
      if (ret) {
        $.notify("<strong>삭제했습니다.</strong>", {
          type: "success",
        });
        loadList(currentData?.paging?.current_page || 1, false);
      } else {
        $.notify("<strong>삭제 실패</strong>", {
          type: "warning",
        });
      }
    },
  });
});

$("body").on("click", "#json_btn", function (e) {
  e.preventDefault();
  const id = $(this).data("id");
  const target = currentData?.list?.find((item) => String(item.id) === String(id));
  if (target) {
    openJsonModal(target);
  }
});

$("body").on("click", "#self_search_btn", function (e) {
  e.preventDefault();
  document.getElementById("search_word").value = $(this).data("title");
  loadList(1);
});

$("body").on("click", "#request_btn", function (e) {
  e.preventDefault();
  const contentCode = $(this).data("content_code");
  if (!contentCode) {
    $.notify("<strong>작품 코드를 찾지 못했습니다.</strong>", {
      type: "warning",
    });
    return;
  }
  window.location.href = "/" + package_name + "/request?code=" + contentCode;
});
})();
