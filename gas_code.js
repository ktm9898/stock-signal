function getAuthPin() {
  const pin = PropertiesService.getScriptProperties().getProperty("AUTH_PIN");
  return pin ? String(pin).trim() : "";
}

function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // 1. Buy Candidates Sheet Header Enforce
  let buySheet = ss.getSheetByName("Buy_Candidates") || ss.insertSheet("Buy_Candidates");
  buySheet.getRange("A1:L1").setValues([["Date", "Ticker", "Name", "Stage", "ADX", "Prev_ADX", "Minus_DI", "Prev_Minus_DI", "Plus_DI", "RSI", "BB_Pct", "ClosePrice"]]);
  buySheet.getRange("A1:L1").setFontWeight("bold").setBackground("#e0f2fe");

  // 2. User Holdings Sheet Header Enforce
  let holdingsSheet = ss.getSheetByName("User_Holdings") || ss.insertSheet("User_Holdings");
  if (holdingsSheet.getLastRow() === 0) {
    holdingsSheet.getRange("A1:E1").setValues([["DateAdded", "Ticker", "Name", "BuyPrice", "Notes"]]);
    holdingsSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#fef3c7");
  }

  // 3. Sell Signals Sheet Header Enforce
  let sellSheet = ss.getSheetByName("Sell_Signals") || ss.insertSheet("Sell_Signals");
  sellSheet.getRange("A1:N1").setValues([["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Prev_ADX", "Minus_DI", "Plus_DI", "RSI", "BB_Pct", "Status", "Details"]]);
  sellSheet.getRange("A1:N1").setFontWeight("bold").setBackground("#fee2e2");

  // 4. Execution Logs Sheet Header Enforce
  let logSheet = ss.getSheetByName("Execution_Logs") || ss.insertSheet("Execution_Logs");
  logSheet.getRange("A1:E1").setValues([["Timestamp", "Status", "ScannedCount", "CandidatesCount", "Message"]]);
  logSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#dcfce7");

  // 5. KOSPI 200 All Metrics Sheet Header Enforce
  let allSheet = ss.getSheetByName("KOSPI200_All_Metrics") || ss.insertSheet("KOSPI200_All_Metrics");
  allSheet.getRange("A1:M1").setValues([["Date", "Ticker", "Name", "ADX", "Prev_ADX", "Minus_DI", "Prev_Minus_DI", "Plus_DI", "Prev_Plus_DI", "RSI", "BB_Pct", "ClosePrice", "Status"]]);
  allSheet.getRange("A1:M1").setFontWeight("bold").setBackground("#f3e8ff");

  // 6. User Holdings Status Sheet Header Enforce
  let hStatusSheet = ss.getSheetByName("User_Holdings_Status") || ss.insertSheet("User_Holdings_Status");
  hStatusSheet.getRange("A1:N1").setValues([["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Prev_ADX", "Minus_DI", "Plus_DI", "RSI", "BB_Pct", "Status", "Details"]]);
  hStatusSheet.getRange("A1:N1").setFontWeight("bold").setBackground("#e0f2fe");
}

function doGet(e) {
  const inputPin = e.parameter.pin ? String(e.parameter.pin).trim() : "";
  const authPin = getAuthPin();
  const action = e.parameter.action || "all";

  if (authPin && inputPin !== authPin && action !== "holdings") {
    return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "Unauthorized: Invalid PIN" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  setupSheets();
  let result = { success: true, status: "success" };

  if (action === "all" || action === "buy") result.buyCandidates = getSheetData(ss.getSheetByName("Buy_Candidates"));
  if (action === "all" || action === "holdings") result.userHoldings = getSheetData(ss.getSheetByName("User_Holdings"));
  if (action === "all" || action === "holdings_status") result.holdingsStatus = getSheetData(ss.getSheetByName("User_Holdings_Status"));
  if (action === "all" || action === "sell") result.sellSignals = getSheetData(ss.getSheetByName("Sell_Signals"));
  if (action === "all" || action === "logs") result.executionLogs = getSheetData(ss.getSheetByName("Execution_Logs"));
  if (action === "all" || action === "all_metrics") result.allMetrics = getSheetData(ss.getSheetByName("KOSPI200_All_Metrics"));

  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const authPin = getAuthPin();

    const inputPin = data.pin ? String(data.pin).trim() : "";
    const isBackendAction = (
      data.action === "update_buy_candidates" || 
      data.action === "update_holdings_status" || 
      data.action === "update_sell_signals"
    );
    if (authPin && inputPin !== authPin && !isBackendAction) {
      return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "Unauthorized: Invalid PIN" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_buy_candidates") {
      setupSheets();
      const buySheet = ss.getSheetByName("Buy_Candidates");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      const todayYMD = extractYMD(new Date());
      
      if (data.candidates && data.candidates.length > 0 && buySheet) {
        const lastRow = buySheet.getLastRow();
        const existingRows = lastRow > 1 ? buySheet.getRange(2, 1, lastRow - 1, buySheet.getLastColumn()).getValues() : [];
        
        data.candidates.forEach(c => {
          const tickerStr = normalizeTicker(c.ticker);
          let exists = false;
          for (let i = 0; i < existingRows.length; i++) {
            const rowYMD = extractYMD(existingRows[i][0]);
            const rowTickerStr = normalizeTicker(existingRows[i][1]);
            if (rowYMD === todayYMD && rowTickerStr === tickerStr) {
              exists = true;
              break;
            }
          }

          // Keep the FIRST signal timestamp & metrics of the day (do not duplicate)
          if (!exists) {
            buySheet.appendRow([today, c.ticker, c.name, c.priority, c.adx, c.prev_adx, c.minus_di, c.prev_minus_di, c.plus_di, c.rsi, (c.b_band_pct !== undefined ? c.b_band_pct : (c.BB_Pct !== undefined ? c.BB_Pct : '-')), c.close]);
          }
        });
      }

      // Record Execution Log
      let logSheet = ss.getSheetByName("Execution_Logs");
      if (data.log) {
        logSheet.appendRow([today, data.log.status || "SUCCESS", data.log.scanned || 0, data.candidates ? data.candidates.length : 0, data.log.message || "정상 완료"]);
      } else {
        logSheet.appendRow([today, "SUCCESS", 200, data.candidates ? data.candidates.length : 0, "정상 완료"]);
      }

      // Record All 200 Stocks Metrics
      if (data.all_stocks && data.all_stocks.length > 0) {
        let allSheet = ss.getSheetByName("KOSPI200_All_Metrics");
        if (allSheet.getLastRow() > 1) {
          allSheet.getRange(2, 1, allSheet.getLastRow() - 1, allSheet.getLastColumn()).clearContent();
        }
        const rows = data.all_stocks.map(s => [
          today, s.ticker, s.name, s.adx, s.prev_adx, s.minus_di, s.prev_minus_di, s.plus_di, s.prev_plus_di, s.rsi, (s.b_band_pct !== undefined ? s.b_band_pct : (s.BB_Pct !== undefined ? s.BB_Pct : '-')), s.close, s.status
        ]);
        allSheet.getRange(2, 1, rows.length, 13).setValues(rows);
      }

      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", count: data.candidates ? data.candidates.length : 0 }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_sell_signals") {
      setupSheets();
      const sheet = ss.getSheetByName("Sell_Signals");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      const todayYMD = extractYMD(new Date());

      if (data.signals && data.signals.length > 0 && sheet) {
        const lastRow = sheet.getLastRow();
        const existingData = lastRow > 1 ? sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues() : [];
        
        data.signals.forEach(s => {
          const tickerStr = normalizeTicker(s.ticker);
          let exists = false;
          for (let i = 0; i < existingData.length; i++) {
            const rowYMD = extractYMD(existingData[i][0]);
            const rowTickerStr = normalizeTicker(existingData[i][1]);
            if (rowYMD === todayYMD && rowTickerStr === tickerStr) {
              exists = true;
              break;
            }
          }

          // Keep the FIRST sell alert timestamp of the day
          if (!exists) {
            const detailsText = Array.isArray(s.details) ? s.details.join(", ") : String(s.details || "");
            sheet.appendRow([
              today, s.ticker, s.name, s.buyPrice, s.currPrice, s.returnRate, 
              s.adx || '-', s.prev_adx || '-', s.minus_di || '-', s.plus_di || '-', s.rsi || '-', 
              (s.b_band_pct !== undefined ? s.b_band_pct : (s.BB_Pct !== undefined ? s.BB_Pct : '-')),
              s.signalLevel, detailsText
            ]);
          }
        });
      }
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_holdings_status") {
      setupSheets();
      const sheet = ss.getSheetByName("User_Holdings_Status");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");

      if (data.holdings_status && data.holdings_status.length > 0 && sheet) {
        if (sheet.getLastRow() > 1) {
          sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
        }
        const rows = data.holdings_status.map(s => [
          today, s.ticker, s.name, s.buyPrice, s.currPrice, s.returnRate, 
          s.adx || '-', s.prev_adx || '-', s.minus_di || '-', s.plus_di || '-', s.rsi || '-', 
          (s.b_band_pct !== undefined ? s.b_band_pct : (s.BB_Pct !== undefined ? s.BB_Pct : '-')),
          s.signalLevel, Array.isArray(s.details) ? s.details.join(", ") : String(s.details || "")
        ]);
        sheet.getRange(2, 1, rows.length, 14).setValues(rows);
      }
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "trigger_screener") {
      const githubToken = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
      if (!githubToken) {
        return ContentService.createTextOutput(JSON.stringify({ 
          success: false, 
          status: "error", 
          message: "구글 앱스 스크립트에 GITHUB_TOKEN 이 설정되어 있지 않습니다. Script Properties에 GITHUB_TOKEN을 추가해주세요." 
        })).setMimeType(ContentService.MimeType.JSON);
      }

      const url = "https://api.github.com/repos/ktm9898/stock-signal/actions/workflows/screener.yml/dispatches";
      const options = {
        method: "post",
        contentType: "application/json",
        headers: {
          "Accept": "application/vnd.github+json",
          "User-Agent": "GoogleAppsScript",
          "Authorization": "Bearer " + githubToken.trim()
        },
        payload: JSON.stringify({ ref: "main" }),
        muteHttpExceptions: true
      };
      
      try {
        const resp = UrlFetchApp.fetch(url, options);
        const code = resp.getResponseCode();
        if (code === 204 || code === 200) {
          return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", message: "수동 스크리닝이 깃허브 서버에서 시작되었습니다." }))
            .setMimeType(ContentService.MimeType.JSON);
        } else {
          return ContentService.createTextOutput(JSON.stringify({ 
            success: false, 
            status: "error", 
            message: "깃허브 API 오류 (HTTP " + code + "): " + resp.getContentText() 
          })).setMimeType(ContentService.MimeType.JSON);
        }
      } catch (err) {
        return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "통신 오류: " + err.toString() }))
          .setMimeType(ContentService.MimeType.JSON);
      }
    }

    if (data.action === "add_user_holding") {
      setupSheets();
      const sheet = ss.getSheetByName("User_Holdings");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd");
      const tickerStr = normalizeTicker(data.ticker);
      sheet.appendRow([today, tickerStr, data.name, data.buyPrice, data.notes || ""]);
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "delete_user_holding") {
      const sheet = ss.getSheetByName("User_Holdings");
      if (sheet && sheet.getLastRow() > 1) {
        const targetTicker = normalizeTicker(data.ticker);
        const targetStr = String(data.ticker).trim();
        const dataRows = sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).getValues();
        for (let i = dataRows.length - 1; i >= 0; i--) {
          const rowTicker = normalizeTicker(dataRows[i][1]);
          const rowName = String(dataRows[i][2] || "").trim();
          if ((targetTicker && rowTicker === targetTicker) || rowName === targetStr || String(dataRows[i][1]).trim() === targetStr) {
            sheet.deleteRow(i + 2);
          }
        }
      }
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "Unknown action" }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function getSheetData(sheet) {
  if (!sheet || sheet.getLastRow() <= 1) return [];
  const rows = sheet.getDataRange().getValues();
  const headers = rows[0];
  const data = [];
  for (let i = 1; i < rows.length; i++) {
    let rowObj = {};
    for (let j = 0; j < headers.length; j++) {
      const key = String(headers[j] || "").trim();
      if (!key) continue;
      let val = rows[i][j];
      if (val instanceof Date) {
        val = Utilities.formatDate(val, "GMT+9", "yyyy-MM-dd HH:mm:ss");
      }
      rowObj[key] = val;
    }
    data.push(rowObj);
  }
  return data;
}

function extractYMD(val) {
  if (!val) return "";
  if (val instanceof Date) {
    return Utilities.formatDate(val, "GMT+9", "yyyyMMdd");
  }
  const str = String(val).trim();
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return Utilities.formatDate(d, "GMT+9", "yyyyMMdd");
  }
  const match = str.match(/(\d{4})[^\d]+(\d{1,2})[^\d]+(\d{1,2})/);
  if (match) {
    const yyyy = match[1];
    const mm = match[2].padStart(2, '0');
    const dd = match[3].padStart(2, '0');
    return yyyy + mm + dd;
  }
  return "";
}

function normalizeTicker(t) {
  if (!t) return "";
  const digits = String(t).replace(/[^0-9]/g, "");
  return digits ? digits.padStart(6, "0") : String(t).trim();
}

/**
 * Automatically triggered by Google Apps Script UI Triggers (⏰ 트리거)
 * to run KOSPI 200 Screener on GitHub Actions.
 */
function triggerGitHubScreener() {
  const githubToken = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  const url = "https://api.github.com/repos/ktm9898/stock-signal/actions/workflows/screener.yml/dispatches";
  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Accept": "application/vnd.github+json",
      "User-Agent": "GoogleAppsScript"
    },
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true
  };
  if (githubToken) {
    options.headers["Authorization"] = "Bearer " + githubToken;
  }
  try {
    UrlFetchApp.fetch(url, options);
  } catch (err) {}
}
