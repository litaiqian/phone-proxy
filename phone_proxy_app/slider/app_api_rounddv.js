const express = require("express");
const { randomUUID } = require("crypto");
const { Blob } = require("buffer");
const { fetch, FormData, ProxyAgent } = require("undici");
const cryptoModule = require("./crypto_module.js");
const buildPdDe3Value = require("./fp.js");
const { generateUA } = require("./ua_generator.js");
const app = express();

// 替换自己的ocr接口 
const OCR_API_URL = "http://127.0.0.1:9898/slide/match/file";
const CAPTCHA_CHECK_URL = "http://c.dun.163.com/api/v3/check";
const GETCONF_URL = "http://c.dun.163.com/api/v2/getconf";
const IR_UP_URL = "http://ir-sdk.dun.163.com/v4/j/up";
const CAPTCHA_GET_URL = "http://c.dun.163.com/api/v3/get";

const CAPTCHA_VERSION = "2.28.5";
const LOAD_VERSION = "2.5.4";
const IR_VERSION = "2.0.13_yanzhengma";
const IR_VK = "d44593ca";

const SESSION_REUSE_LIMIT = 3;
let _currentSession = null;
let _sessionUseCount = 0;

function buildNewSession() {
  const { ua, deviceId, bsDvid, parts } = generateUA();
  return {
    ua,
    deviceId,
    bsDvid,
    parts,
    dt: "",
  };
}

function acquireSession() {
  if (!_currentSession || _sessionUseCount >= SESSION_REUSE_LIMIT) {
    _currentSession = buildNewSession();
    _sessionUseCount = 0;
    console.log(`[UA会话] 生成新会话 | device=${_currentSession.parts.device} android=${_currentSession.parts.androidVersion} chrome=${_currentSession.parts.chromeVersion}`);
    // console.log(`[UA会话] device-id=${_currentSession.deviceId}`);
  }
  _sessionUseCount += 1;
  // console.log(`[UA会话] 复用会话 ${_sessionUseCount}/${SESSION_REUSE_LIMIT} | device-id=${_currentSession.deviceId}`);
  return _currentSession;
}
const KEPUCHINA_FP_ARRAY = ["38974258425244", "39631003042944"];
const IR_UP_D = `JgaYPDePT/o9DatgdURG.pvHtMK0ZPS1JSgJcuDq9ZdGz9zA+KVZfU1GmXYhHj2q6iDJhcc6ew5rFDLxRJEjYbce9XTym8r6Yce2tufO50gmxf3UQcTu6h3iKHhHumUqkC6bcdmcHKJa0zRWIBIlh0AhLMvXk5w.UPeKw+GAY4VLheJzIx1wdtRM2waimMdP4e16EEAG9XEdCbup.pd+FW8rcBpJl/VgUsKislTBnye1sci1Eo6+sN31zCg1yukyvqnv+cHK9.fzlHL0t+mGKYxzQGz6CyUiOmt4L0RVDb+UsMl5PKVoIHo0zDwqzBkpE9BaMnbojh30j.58z0b+JbCmJW.eN.1mBpuwZyR+0F2jNL2UWoTyirDfIL0Cw2v9bpwaKF3kpWAhUDEvOJjP9J8Ea/PixmyRUJSbHSHQqQV55XZQUH3KnVJNNWN1Kn9x9f.HJg239yIT+OU/.eIIGNEs4AJuozj5SmJbvJhk3.ZQptEHhCZCkggQBbDERylXdwVgOsgvj/v2kxo.I5V.mXxlNyXHDD9kU+DtyLDfwkiccSi/eZt3cW+0+VpOrucLjzh34ZsvvQgH4a+/ylp.BTCAn68113YBCRaHOnQw6JaKZTk/YMN/aRcF0nYV.qAtJBt.NrOhVXezDLBaG6hr8vYqd9YIjpP8UbUsoEj1C9RO1kMWEjMmo9lRZy/MMGdaclm4U99N+6gZDEgkRpEhKXtLBew5EAUoMILmulUVYl5pt+WPdlz1uteIcGLR9C/lz9PKy.kUD1DBKiEFtasHPrh.VxqDeJZQmhCBygKKRDm.R.QbU0I36rwqEr53Lm92E1TWHkqkwUYeAdXsYzlu6EU8ulNvdRkAY5OoH6RftU8wYrMwweEOmmsJe4ALmPJs.sISqzalyfNkUc4/Ua5df9M.0BL/uBi9Jh6F3c.gfBVvjNc+ASt6QNhk62Gy9kRPDSyg8EF82ymG1xI24rnMigBYBjBcUKvOCq0YDuud5WEQpWkLFkTZ3kZo9p3WcsXaAAgVe2ecMlYacVP4RR66aoyvWph3QFmvM/4finNu+hhUc46H5bsKda4K0jUsKr12aI9ws6.AjEod4NfZGCCnm9sLGBOdPQObCNcuDukACnvY3usLFurwBKo5iXzANq6Xz3FRTYzc+QUsSFTOu9rVIB5mLkjcL8YTo0.t9KUTKhQV8UCxOqv3n9sYi3Hzeq1QqipprZPDmh6yjDoTkO6SFBXL2PvC3fi2YLpSf+KTTag44iIyoMpuCcqwBJdgI0.gXeHFv2SI109ix65ds0FH6qA/ZawFFJUUh4YyF8/Np4wu5Wo+5JpQf/oCzXiJVqym9rNcRbIjGRkV4chEfwlsu/MEMDK6xiO6WKgoIHohS9bgex9xFNHV64hn5T8Vm33dK5X4U1wOmBkwDgftuAXJGQQ8CIG6uztotlFkUdUehTm1BXVFlLqii3Ev/hVoHU3Etiwh5UGgG1H0vfNwfnL48YTXDjzr6CLypwnh2K5Bt5a5HZ9E9ddAKD5vvSm1BCzq6by9QZ.2Y/RlxtuH6+mxMwMP9653nBx+C8P2iYxnLivdCu/.txUGgxXQwtYH1Mibt3gSAws8XKzFIrLp9lelFquLnjVY.mPMoKQ1WrhEK5p0unBTT4h08zvIPMDe+9btiosoajwNkrHBajSm+8EAPe42c4yckztwd4kWbvw3LKh3.gc/b6qxGQzABoqQ0WbFhzO690C1AMWijVAGY1uzayIdhJF+1Ureei/QVAs8ZiI5BF33Zwe4SiNd8h5om1zN4xXvL8EyBtSVw0vXCvvmniq+VYKA+aGzLREAi61dnJm4S5XgBKCkscYiRyi6ictGXwpMhKrDwgplYqdrXML2pBK6QZLyRSgMvsFiJpATdp8poMJfVSDB2DgsvEjcy3aoXSHBU2Q4fLGAJ./v5NFvQVH2jsN901EO0FFAMqiUQPTiOICrgbUnPRIz1MIkdTm2jIeO5UtLLxHD+vETYAmTRaKyFv9MYe05n9lI0FDtT4sBIzr4Mrrb2OUuqHhk8nbO5SIJdm9Ul81jy/DBsfdSBeSr/5M9Pq.2YYSrxj/TIw1ldtoVlHY4MLrNRYAYeo+lmiQaJe2ojgONrEo/RV/lADIVOJg7`;

// 代理配置：
const PROXY_URL = normalizeProxyUrl(process.env.YIDUN_PROXY_URL || process.env.PROXY_URL || "");
const PROXY_DEBUG = String(process.env.YIDUN_PROXY_DEBUG || "1") !== "0";
const _proxyDispatcherCache = new Map();
const _proxyFetchLogCache = new Set();

function generateIrUpD(appId, version, nonce, session) {
  const fpUa = session.ua;
  const fpUaTrimmed = fpUa.replace(/^Mozilla\//, "");
  const features = [
    [218, 1, 0], [225, 1, 1], [252, 100, "44100,2,2,2,2,max,speakers"], [254, 1, 1],
    [253, 30, "114.0.0.0"], [261, 1, 2], [262, 30, "0.0.0.0"],
    [263, 8, 2, 3, 0, 1, 2, 2, 2, 2], // matchMedia 特征
    [265, 400, ""], [279, 5, "22222"], [280, 1, 33], [283, 500, ""],
    [501, 1, 0], [503, 32, "22222222"], [505, 3, "222"],
    [509, 30, "function(){return[nativecode]}"], [508, 4, 0, 0],
    [510, 15, "stun:stun.l.google.com:19302"], [511, 32, ""], [512, 1, 0], [513, 100, "茅台"],
    [700, 200, "https://h5.moutai519.com.cn/"], [713, 4, 393, 851], // Client Size
    [800, 8, "5bf1626b"], [801, 8, ""], [802, 8, "e5cd4de6"],
    [803, 8, "a4c622e1"], [804, 8, "89e7c489"], [902, 16, "5b8f6c40049ed4e0"],
    [904, 16, "7dfd6ff2168393de"], // Audio/Math Hash
    [200, 400, fpUa],
    [201, 20, "zh-CN"], [202, 1, 24], [203, 1, 24], [206, 1, -8], // Timezone
    [207, 1, 1], [208, 1, 1], [209, 1, 1], [210, 1, 0], [211, 1, 1],
    [213, 10, "Linux arm8l"], [214, 15, "unknown"],
    [216, 16, "7320f78dfeb22a46"], [217, 16, "5a27867205423871"], // Canvas & WebGL Hash
    [223, 1, 1], [228, 1, 0], [229, 1, 0],
    [233, 400, fpUaTrimmed],
    [234, 64, "zh-CN,zh,en-US,en"], [238, 40, ""], [239, 20, ""],
    [242, 2, 393, 851, 393, 851], [243, 1, 8], [250, 1, 0], [251, 1, -1], [258, 1, 8],
    [260, 4, 4096], [264, 1, 5], [267, 1, 24], [273, 16, "e3b0c44298fc1c14"],
    [901, 200, "Google Inc. (ARM):Mali-G77"], [506, 1, 0], [502, 4, 100, 2, -1, -1],
    [255, 20, "UTF-8"], [257, 20, ""], [900, 16, "8a5cfdb0bb72fa19"],
    [500, 100, "1111111111111111111"],
    [284, 400, `arm,HUAWEI_${session.parts.chromeVersion},HUAWEI_${session.parts.chromeVersion},true,64,${session.parts.device},Android,${session.parts.androidVersion}`],
    [911, 1, 0], [912, 4, 110], [913, 4, 0], [914, 100, "1,1"],
    [922, 100, ""], [963, 400, "https://h5.moutai519.com.cn/"], [964, 1, 2]
  ];

  const contextInfo = [
    [2, 32, appId],
    [3, 32, ""], 
    [4, 20, version],
    [5, 32, nonce],
    [6, 16, Date.now().toString()],
    [515, 4, 105], [516, 4, 120],
    [121, 32, "init:1-gts:1"],
    [910, 400, ""], [278, 4, 110],
    [3006, 400, ""], [3007, 400, nonce],
    [971, 4, 200], [972, 4, 0]
  ];

  const listenerInfo = [
    [110, 2, 0], [111, 2, 0], [112, 2, 0], [113, 2, 0], [114, 2, 0], [115, 2, 0],
    [116, 2, 0], [117, 2, 0], [118, 2, 0], [119, 2, 0], [120, 2, 0], [967, 2, 0], [968, 2, 0]
  ];

  const chunks = [...features, ...contextInfo, ...listenerInfo];

  for (let i = chunks.length; i;) {
    const r = Math.floor(Math.random() * i--);
    const temp = chunks[i];
    chunks[i] = chunks[r];
    chunks[r] = temp;
    
  }

  const plainText = chunks.reduce((acc, val) => acc.concat(val), []).join(",");

  return cryptoModule.encryptWithAes(plainText);
}

function normalizeProxyUrl(proxyUrl) {
  if (proxyUrl === undefined || proxyUrl === null) return "";
  let value = String(proxyUrl).trim();
  if (!value) return "";
  if (!/^[a-zA-Z][a-zA-Z\d+.-]*:\/\//.test(value)) value = `http://${value}`;
  return value;
}

function maskProxyUrl(proxyUrl) {
  const normalized = normalizeProxyUrl(proxyUrl);
  if (!normalized) return "未启用";
  try {
    const urlObj = new URL(normalized);
    if (urlObj.username) urlObj.username = "***";
    if (urlObj.password) urlObj.password = "***";
    return urlObj.toString();
  } catch (e) {
    return normalized.replace(/:\/\/([^:@/]+):([^@/]+)@/, "://***:***@");
  }
}

function getProxyUsageInfo(proxyUrlOverride) {
  if (proxyUrlOverride !== undefined) {
    const requestProxyUrl = normalizeProxyUrl(proxyUrlOverride);
    return {
      enabled: Boolean(requestProxyUrl),
      url: requestProxyUrl,
      source: requestProxyUrl ? "请求参数proxyUrl" : "请求参数proxyUrl为空，强制直连",
      label: requestProxyUrl ? maskProxyUrl(requestProxyUrl) : "未启用",
    };
  }
  return {
    enabled: Boolean(PROXY_URL),
    url: PROXY_URL,
    source: PROXY_URL ? "环境变量YIDUN_PROXY_URL/PROXY_URL" : "未配置",
    label: PROXY_URL ? maskProxyUrl(PROXY_URL) : "未启用",
  };
}

function getProxyDispatcher(proxyUrl) {
  const normalizedProxyUrl = normalizeProxyUrl(proxyUrl);
  if (!normalizedProxyUrl) return undefined;

  if (_proxyDispatcherCache.has(normalizedProxyUrl)) return _proxyDispatcherCache.get(normalizedProxyUrl);

  try {
    const dispatcher = new ProxyAgent(normalizedProxyUrl);
    _proxyDispatcherCache.set(normalizedProxyUrl, dispatcher);
    if (PROXY_DEBUG) console.log(`[代理] ProxyAgent创建成功: ${maskProxyUrl(normalizedProxyUrl)}`);
    return dispatcher;
  } catch (e) {
    const message = `代理创建失败: ${maskProxyUrl(normalizedProxyUrl)} | ${e.message}`;
    console.error(`[代理] ${message}`);
    throw new Error(message);
  }
}

function isPrivateOrLocalUrl(requestUrl) {
  try {
    const { hostname } = new URL(requestUrl);
    const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (host === "localhost" || host === "::1") return true;
    const parts = host.split(".").map(Number);
    if (parts.length !== 4 || parts.some(n => !Number.isInteger(n) || n < 0 || n > 255)) return false;
    return parts[0] === 10
      || parts[0] === 127
      || (parts[0] === 192 && parts[1] === 168)
      || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
      || (parts[0] === 169 && parts[1] === 254);
  } catch (e) {
    return false;
  }
}

function fetchWithProxy(url, options = {}, proxyUrlOverride) {
  const bypassProxy = isPrivateOrLocalUrl(url);
  const proxyInfo = bypassProxy
    ? { enabled: false, url: "", source: "本机/内网地址自动直连", label: "未启用" }
    : getProxyUsageInfo(proxyUrlOverride);
  const dispatcher = proxyInfo.enabled ? getProxyDispatcher(proxyInfo.url) : undefined;

  if (PROXY_DEBUG) {
    try {
      const target = new URL(url).host;
      const logKey = `${target}|${proxyInfo.enabled ? proxyInfo.url : "DIRECT"}`;
      if (!_proxyFetchLogCache.has(logKey)) {
        _proxyFetchLogCache.add(logKey);
        console.log(`[代理] 出站请求 ${target} | ${proxyInfo.enabled ? "走代理" : "直连"} | ${proxyInfo.label} | 来源: ${proxyInfo.source}`);
      }
    } catch (e) {}
  }

  const requestPromise = dispatcher ? fetch(url, { ...options, dispatcher }) : fetch(url, options);
  return requestPromise.catch((e) => {
    let target = String(url);
    try { target = new URL(url).host; } catch (err) {}
    const prefix = proxyInfo.enabled
      ? `代理请求失败 | 目标: ${target} | 代理: ${proxyInfo.label}`
      : `直连请求失败 | 目标: ${target}`;
    const wrappedError = new Error(`${prefix} | ${e.message}`);
    wrappedError.cause = e;
    throw wrappedError;
  });
}


function getFilenameFromUrl(url, fallbackName) {
  try {
    return new URL(url).pathname.split("/").pop() || fallbackName;
  } catch (error) {
    return fallbackName;
  }
}

async function fetchImageAsBlob(imageUrl, fallbackName, proxyUrl) {
  const response = await fetchWithProxy(imageUrl, {}, proxyUrl);
  if (!response.ok) throw new Error(`图片下载失败 (${response.status}): ${imageUrl}`);
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const bytes = Buffer.from(await response.arrayBuffer());
  return {
    blob: new Blob([bytes], { type: contentType }),
    filename: getFilenameFromUrl(imageUrl, fallbackName),
  };
}

function parseOcrResponseText(responseText) {
  try { return JSON.parse(responseText); } catch (e) {}
  try { return JSON.parse(responseText.replace(/'/g, '"')); } catch (e) {}
  try { return Function(`"use strict"; return (${responseText});`)(); } catch (e) {
    throw new Error(`OCR 接口返回内容无法解析`);
  }
}

function randomString(length) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from({ length }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
}

function generateJsonpCallback(suffix) {
  return `__JSONP_${randomString(7)}_${suffix}`;
}

function parseJsonpResponse(responseText) {
  const trimmedText = responseText.trim();
  try { return JSON.parse(trimmedText); } catch (e) {}
  const match = trimmedText.match(/^[^(]+\(([\s\S]+)\)\s*;?\s*$/);
  if (!match) throw new Error(`无法解析 JSONP 响应`);
  return JSON.parse(match[1]);
}

function buildUrlWithParams(baseUrl, params) {
  const url = new URL(baseUrl);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  });
  return url.toString();
}

function normalizeCaptchaDataPayload(dataPayload) {
  if (dataPayload == null) return "";
  if (typeof dataPayload === "string") {
    try {
      return JSON.stringify(JSON.parse(dataPayload.trim()));
    } catch (e) {
      return dataPayload.trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean).join("");
    }
  }
  return JSON.stringify(dataPayload);
}

function createUuid32() {
  return randomUUID().replace(/-/g, "");
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}

function getCommonHeaders(session, extraHeaders) {
  return { "User-Agent": session.ua, ...extraHeaders };
}

async function fetchJsonp(url, headers, proxyUrl) {
  const response = await fetchWithProxy(url, { headers }, proxyUrl);
  const responseText = await response.text();
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  return parseJsonpResponse(responseText);
}

// --- 核心业务逻辑修改（接收参数） ---

async function getSlideTargetFromImageUrls(targetImageUrl, backgroundImageUrl, ocrApiUrl = OCR_API_URL, proxyUrl) {
  const [targetFile, backgroundFile] = await Promise.all([
    fetchImageAsBlob(targetImageUrl, "target.png", proxyUrl),
    fetchImageAsBlob(backgroundImageUrl, "background.jpg", proxyUrl),
  ]);

  const formData = new FormData();
  formData.append("target_img", targetFile.blob, targetFile.filename);
  formData.append("bg_img", backgroundFile.blob, backgroundFile.filename);

  const response = await fetchWithProxy(ocrApiUrl, { method: "POST", body: formData }, proxyUrl);
  const responseText = await response.text();
  if (!response.ok) throw new Error(`OCR 接口请求失败`);

  const data = parseOcrResponseText(responseText);
  if (!data || !Array.isArray(data.target) || data.target.length === 0) {
    throw new Error(`OCR 返回缺少 target`);
  }
  return { targetX: data.target[0] };
}

async function getConf(captchaId, pageUrl, session, proxyUrl) {
  const params = {
    referer: pageUrl,
    zoneId: "",
    dt: session.dt || undefined,
    id: captchaId,
    ipv6: "false",
    runEnv: "10",
    iv: "5",
    loadVersion: LOAD_VERSION,
    lang: "zh-CN",
    callback: generateJsonpCallback(0),
  };

  const result = await fetchJsonp(buildUrlWithParams(GETCONF_URL, params), getCommonHeaders(session, { Accept: "*/*", Referer: pageUrl }), proxyUrl);
  if (!result || !result.data || !result.data.dt || !result.data.ir || !result.data.ir.pn) {
    throw new Error(`getconf 异常`);
  }
  session.dt = result.data.dt;
  return result.data;
}

async function postIrUp(irConfig, pageUrl, session, proxyUrl) {
  const nonce = createUuid32();
  const dynamicD = generateIrUpD(irConfig.pn, IR_VERSION, nonce, session);
  const payload = {
    p: irConfig.pn,
    v: IR_VERSION,
    vk: IR_VK,
    n: nonce,
    d: dynamicD
  };

  const response = await fetchWithProxy(IR_UP_URL, {
    method: "POST",
    headers: getCommonHeaders(session, {
      Accept: "*/*",
      Origin: pageUrl.replace(/\/$/, ""),
      Referer: pageUrl,
      "content-type": "text/plain",
    }),
    body: JSON.stringify(payload),
  }, proxyUrl);

  const responseText = await response.text();
  if (!response.ok) throw new Error(`ir up 请求失败`);
  const result = JSON.parse(responseText);
  return result.data;
}

function generateFp(pageHost) {
  return buildPdDe3Value({ host: pageHost, fpArray: KEPUCHINA_FP_ARRAY });
}

async function getCaptchaData(confData, irUpData, fpValue, captchaId, pageUrl, session, proxyUrl) {
  const cbValue = cryptoModule.generateCbValue();
  const params = {
    referer: pageUrl,
    zoneId: confData.zoneId || "CN31",
    dt: confData.dt,
    irToken: irUpData.tk,
    id: captchaId,
    fp: fpValue,
    https: "false",
    type: "",
    version: CAPTCHA_VERSION,
    dpr: "1",
    dev: "3",
    cb: cbValue,
    ipv6: "false",
    runEnv: "10",
    group: "",
    scene: "",
    lang: "zh-CN",
    sdkVersion: "",
    loadVersion: LOAD_VERSION,
    iv: "4",
    user: "",
    width: "320",
    audio: "false",
    sizeType: "10",
    smsVersion: "v3",
    token: "",
    callback: generateJsonpCallback(0),
  };
  return fetchJsonp(buildUrlWithParams(CAPTCHA_GET_URL, params), getCommonHeaders(session, { Accept: "*/*", Referer: pageUrl }), proxyUrl);
}

async function n1(captchaId, pageUrl, pageHost, session, proxyUrl) {
  const confData = await getConf(captchaId, pageUrl, session, proxyUrl);
  const irUpData = await postIrUp(confData.ir, pageUrl, session, proxyUrl);
  const fpValue = generateFp(pageHost);
  const captchaResponse = await getCaptchaData(confData, irUpData, fpValue, captchaId, pageUrl, session, proxyUrl);
  return {
    fp: fpValue, fpArray: KEPUCHINA_FP_ARRAY, dt: confData.dt,
    irPn: confData.ir.pn, irToken: irUpData.tk, response: captchaResponse,
  };
}

async function checkCaptcha(dt, id, token, dataPayload, pageUrl, captchaOptions = {}, session, proxyUrl) {
  const cbValue = cryptoModule.generateCbValue();
  const zoneId = captchaOptions.zoneId || "CN31";
  const params = {
    referer: pageUrl, zoneId: zoneId, dt: dt, id: id, token: token, data: normalizeCaptchaDataPayload(dataPayload),
    width: String(captchaOptions.width || "320"), type: String(captchaOptions.type == null ? 2 : captchaOptions.type),
    version: CAPTCHA_VERSION, cb: cbValue, user: "", extraData: captchaOptions.priorityRecordId == null ? "" : JSON.stringify({ priorityRecordId: Number(captchaOptions.priorityRecordId) }), bf: String(captchaOptions.bf == null ? 0 : captchaOptions.bf),
    runEnv: "10", sdkVersion: "", loadVersion: LOAD_VERSION, iv: "4", callback: generateJsonpCallback(1),
  };

  const response = await fetchWithProxy(buildUrlWithParams(CAPTCHA_CHECK_URL, params), {
    headers: getCommonHeaders(session, { Accept: "*/*", Referer: pageUrl }),
  }, proxyUrl);
  const responseText = await response.text();
  const parsed = parseJsonpResponse(responseText);
  if (parsed && parsed.data && parsed.data.validate && captchaOptions.fingerprint) {
    parsed.data.finalValidate = cryptoModule.buildFinalValidate(parsed.data.validate, captchaOptions.fingerprint, zoneId);
  }
  return parsed;
}

async function res_data(token, drag, trackOptions) {
  const { d, p, f, ext } = cryptoModule.buildTraceData(token, drag, trackOptions);
  return { d, m: "", p, f, ext };
}

async function runCaptchaFlow(captchaId, pageUrl, ocrApiUrl, proxyUrl, priorityRecordId) {
  let pageHost;
  try {
    pageHost = new URL(pageUrl).hostname;
  } catch (e) {
    throw new Error("提供的 PAGE_URL 格式不合法");
  }

  const effectiveProxyUrl = proxyUrl !== undefined ? proxyUrl : (PROXY_URL || undefined);
  const effectiveOcrApiUrl = ocrApiUrl || OCR_API_URL;

  const session = acquireSession();

  const get_res = await n1(captchaId, pageUrl, pageHost, session, effectiveProxyUrl);
  const captchaData = get_res.response.data;
  const juli = await getSlideTargetFromImageUrls(captchaData.front[0], captchaData.bg[0], effectiveOcrApiUrl, effectiveProxyUrl);
  const body = await res_data(captchaData.token, juli.targetX, { width: 320 });
  await sleep(captchaData.waitTime || 300);

  const checkRes = await checkCaptcha(get_res.dt, captchaId, captchaData.token, body, pageUrl, {
    zoneId: captchaData.zoneId,
    type: captchaData.type,
    width: 320,
    bf: 0,
    fingerprint: get_res.fp,
    priorityRecordId,
  }, session, effectiveProxyUrl);
  const checkData = checkRes && checkRes.data && typeof checkRes.data === "object" ? checkRes.data : {};
  return {
    ...checkData,
    fp: get_res.fp,
    deviceId: session.deviceId,
    userAgent: session.ua,
  };
}

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// --- Express API 路由 ---
app.post("/api/verify", async (req, res) => {
  const { captchaId, pageUrl, ocrApiUrl, proxyUrl, priorityRecordId } = req.body;
  
  if (!captchaId || !pageUrl) {
    return res.status(400).json({ success: false, error: "缺少必要参数：captchaId 或 pageUrl" });
  }

  try {
    const proxyInfo = getProxyUsageInfo(proxyUrl);
    console.log(`[代理] 本次代理: ${proxyInfo.enabled ? "启用" : "未启用"} | ${proxyInfo.label} | 来源: ${proxyInfo.source}`);
    const result = await runCaptchaFlow(captchaId, pageUrl, ocrApiUrl, proxyUrl, priorityRecordId); 
    res.json({ success: true, data: result, message: "接口调用成功" });
  } catch (error) {
    console.error("【接口内部报错】:", error); 
    res.status(500).json({ success: false, error: error.message });
  }
});

const PORT = 8887;
app.listen(PORT, () => {
  console.log(`本地滑块 API 服务已启动！请勿关闭此窗口。`);
  console.log(`调用地址: http://127.0.0.1:${PORT}/api/verify`);
  console.log(`默认代理: ${PROXY_URL ? maskProxyUrl(PROXY_URL) : "未配置"}`);
  console.log(`proxyUrl示例: http://127.0.0.1:7897；传空字符串""表示本次强制直连`);
});
