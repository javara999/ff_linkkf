let currentCate = "ing";
let nextPage = 2;
let totalPage = 1;
let isLoading = false;

const spinner = document.getElementById("spinner");
const listContainer = document.getElementById("screen_movie_list");
const categoryButtons = document.querySelectorAll("#anime_category button");

const categoryConfig = {
  ing: {
    endpoint: "anime_list",
    makeData: (page) => ({ page: String(page), type: "ing" }),
    title: "애니",
  },
  movie: {
    endpoint: "screen_movie_list",
    makeData: (page) => ({ page: String(page) }),
    title: "극장판",
  },
  complete: {
    endpoint: "complete_anilist",
    makeData: (page) => ({ page: String(page) }),
    title: "성인",
  },
  top_view: {
    endpoint: "anime_list",
    makeData: (page) => ({ page: String(page), type: "top_view" }),
    title: "최신",
  },
};

function setLoading(flag) {
  isLoading = flag;
  spinner.style.display = flag ? "block" : "none";
}

function setActiveCategory(cate) {
  categoryButtons.forEach((button) => {
    button.classList.toggle("active", button.id === cate);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function getImageUrl(imageLink) {
  const image = String(imageLink || "").trim();
  return image === "" ? placeholder_image : image;
}

function renderEmpty(message) {
  listContainer.innerHTML = `<div class="alert alert-secondary mt-2">${escapeHtml(message)}</div>`;
}

function openPlayerPage(url) {
  if (!url) {
    $.notify("<strong>재생 URL을 찾지 못했습니다.</strong>", {
      type: "warning",
    });
    return;
  }
  window.open(url, "_blank");
}

async function playLatest(code, title) {
  try {
    const response = await fetch(`/${package_name}/ajax/play_latest`, {
      method: "POST",
      cache: "no-cache",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        code: String(code || ""),
        title: String(title || ""),
      }),
    });
    const ret = await response.json();
    if (ret.ret !== "success" || ret.data == null) {
      $.notify(`<strong>${escapeHtml(ret.log || "재생 정보를 가져오지 못했습니다.")}</strong>`, {
        type: "warning",
      });
      return;
    }
    openPlayerPage(ret.data.play_url);
  } catch (error) {
    console.error(error);
    $.notify("<strong>재생 정보를 가져오지 못했습니다.</strong>", {
      type: "warning",
    });
  }
}

function renderItems(ret, append = false) {
  const items = Array.isArray(ret.episode) ? ret.episode : [];
  const page = Number(ret.page || 1);
  const title = categoryConfig[currentCate]?.title || "목록";

  if (items.length === 0 && append === false) {
    renderEmpty(`${title} 목록이 없습니다.`);
    return;
  }

  let html = "";
  if (append === false) {
    html += `<div id="page_caption" style="padding-bottom: 3px">`;
    html += `<button type="button" class="btn btn-info">${escapeHtml(title)}</button>`;
    html += `</div>`;
    html += `<div id="inner_screen_movie" class="row infinite-scroll">`;
  }

  for (const item of items) {
    const code = escapeHtml(item.code);
    const titleText = escapeHtml(item.title);
    const chapter = escapeHtml(item.chapter || "");
    const imageUrl = escapeHtml(getImageUrl(item.image_link));

    html += `<div class="col-6 col-sm-4 col-md-3 mb-3">`;
    html += `<div class="card h-100">`;
    html += `<img class="card-img-top" src="${imageUrl}" alt="${titleText}" loading="lazy" style="cursor: pointer" onclick="location.href='${request_path}?code=${code}'" />`;
    if (chapter !== "") {
      html += `<span class="badge badge-danger badge-on-image">${chapter}</span>`;
    }
    html += `<div class="card-body d-flex flex-column">`;
    html += `<h5 class="card-title">${titleText}</h5>`;
    html += `<a href="${request_path}?code=${code}" class="btn btn-primary btn-sm mb-2">분석</a>`;
    html += `<button type="button" class="btn btn-outline-info btn-sm play-latest-btn" data-code="${code}" data-title="${titleText}">최신화 보기</button>`;
    html += `</div>`;
    html += `</div>`;
    html += `</div>`;
  }

  if (append === false) {
    html += `</div>`;
    listContainer.innerHTML = html;
  } else {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    const target = document.getElementById("inner_screen_movie");
    while (wrapper.firstChild) {
      target.appendChild(wrapper.firstChild);
    }
  }

  if (page >= totalPage) {
    nextPage = totalPage + 1;
  } else {
    nextPage = page + 1;
  }
}

async function fetchCategory(cate, page = 1, append = false) {
  const config = categoryConfig[cate];
  if (config === undefined || isLoading) {
    return;
  }

  currentCate = cate;
  setActiveCategory(cate);
  setLoading(true);

  try {
    const response = await fetch(`/${package_name}/ajax/${config.endpoint}`, {
      method: "POST",
      cache: "no-cache",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams(config.makeData(page)),
    });
    const ret = await response.json();
    if (ret.ret !== "success") {
      renderEmpty(ret.log || "목록을 불러오지 못했습니다.");
      return;
    }
    totalPage = Number(ret.total_page || 1);
    renderItems(ret, append);
  } catch (error) {
    console.error(error);
    renderEmpty("목록을 불러오지 못했습니다.");
  } finally {
    setLoading(false);
  }
}

async function runSearch() {
  const input = document.getElementById("input_search");
  const query = input.value.trim();
  if (query === "" || isLoading) {
    return;
  }

  setLoading(true);
  try {
    const response = await fetch(`/${package_name}/ajax/search`, {
      method: "POST",
      cache: "no-cache",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ query }),
    });
    const ret = await response.json();
    if (ret.ret !== "success") {
      renderEmpty(ret.log || "검색 결과를 불러오지 못했습니다.");
      return;
    }

    currentCate = "search";
    setActiveCategory("");
    totalPage = 1;
    nextPage = 2;
    const result = {
      page: 1,
      total_page: 1,
      episode: Array.isArray(ret.episode) ? ret.episode : [],
    };
    renderItems(result, false);
    if (result.episode.length === 0) {
      renderEmpty(`"${query}" 검색 결과가 없습니다.`);
    }
  } catch (error) {
    console.error(error);
    renderEmpty("검색 결과를 불러오지 못했습니다.");
  } finally {
    setLoading(false);
  }
}

function loadNextPage() {
  if (isLoading) {
    return;
  }
  if (currentCate === "search" || currentCate === "top_view") {
    return;
  }
  if (nextPage > totalPage) {
    return;
  }
  fetchCategory(currentCate, nextPage, true);
}

function onCategoryClick(event) {
  const cate = event.target.id;
  if (categoryConfig[cate] === undefined) {
    return;
  }
  nextPage = 2;
  totalPage = 1;
  fetchCategory(cate, 1, false);
}

function onScroll() {
  const threshold = 50;
  const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
  if (clientHeight + scrollTop + threshold >= scrollHeight) {
    loadNextPage();
  }
}

function debounce(func, delay) {
  let timeoutId = null;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => func(...args), delay);
  };
}

document.getElementById("anime_category").addEventListener("click", onCategoryClick);
document.getElementById("btn_search").addEventListener("click", runSearch);
document.getElementById("input_search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runSearch();
  }
});
document.addEventListener("scroll", debounce(onScroll, 250));

document.body.addEventListener("click", (event) => {
  const button = event.target.closest(".play-latest-btn");
  if (!button) {
    return;
  }
  event.preventDefault();
  playLatest(button.dataset.code, button.dataset.title);
});

document.addEventListener("DOMContentLoaded", () => {
  fetchCategory("ing", 1, false);
});
