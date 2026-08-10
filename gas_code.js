function getAuthPin() {
  const pin = PropertiesService.getScriptProperties().getProperty("AUTH_PIN");
  return pin ? String(pin).trim() : "";
}

function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // 1. Buy Candidates Sheet Header Enforce
  let buySheet = ss.getSheetByName("Buy_Candidates") || ss.insertSheet("Buy_Candidates");
  buySheet.getRange("A1:K1").setValues([["Date", "Ticker", "Name", "Tier", "ADX", "Prev_ADX", "Minus_DI", "Prev_Minus_DI", "Plus_DI", "RSI", "ClosePrice"]]);
  buySheet.getRange("A1:K1").setFontWeight("bold").setBackground("#e0f2fe");

  // 2. User Holdings Sheet Header Enforce
  let holdingsSheet = ss.getSheetByName("User_Holdings") || ss.insertSheet("User_Holdings");
  if (holdingsSheet.getLastRow() === 0) {
    holdingsSheet.getRange("A1:E1").setValues([["DateAdded", "Ticker", "Name", "BuyPrice", "Notes"]]);
    holdingsSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#fef3c7");
  }

  // 3. Sell Signals Sheet Header Enforce
  let sellSheet = ss.getSheetByName("Sell_Signals") || ss.insertSheet("Sell_Signals");
  if (sellSheet.getLastRow() === 0) {
    sellSheet.getRange("A1:I1").setValues([["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Status", "Details"]]);
    sellSheet.getRange("A1:I1").setFontWeight("bold").setBackground("#fee2e2");
  }

  // 4. Execution Logs Sheet Header Enforce
  let logSheet = ss.getSheetByName("Execution_Logs") || ss.insertSheet("Execution_Logs");
  logSheet.getRange("A1:E1").setValues([["Timestamp", "Status", "ScannedCount", "CandidatesCount", "Message"]]);
  logSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#dcfce7");

  // 5. KOSPI 200 All Metrics Sheet Header Enforce
  let allSheet = ss.getSheetByName("KOSPI200_All_Metrics") || ss.insertSheet("KOSPI200_All_Metrics");
  allSheet.getRange("A1:K1").setValues([["Date", "Ticker", "Name", "ADX", "Prev_ADX", "Minus_DI", "Prev_Minus_DI", "Plus_DI", "RSI", "ClosePrice", "Status"]]);
  allSheet.getRange("A1:K1").setFontWeight("bold").setBackground("#f3e8ff");
}

function doGet(e) {
  const inputPin = e.parameter.pin ? String(e.parameter.pin).trim() : "";
  const authPin = getAuthPin();

  if (inputPin !== authPin) {
    return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "Unauthorized: Invalid PIN" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const action = e.parameter.action || "all";
  let result = { success: true, status: "success" };

  if (action === "all" || action === "buy") result.buyCandidates = getSheetData(ss.getSheetByName("Buy_Candidates"));
  if (action === "all" || action === "holdings") result.userHoldings = getSheetData(ss.getSheetByName("User_Holdings"));
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
    if (inputPin !== authPin && data.action !== "update_buy_candidates") {
      return ContentService.createTextOutput(JSON.stringify({ success: false, status: "error", message: "Unauthorized: Invalid PIN" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_buy_candidates") {
      setupSheets();
      const buySheet = ss.getSheetByName("Buy_Candidates");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      const todayDateStr = today.substring(0, 10);
      
      if (data.candidates && data.candidates.length > 0 && buySheet) {
        const lastRow = buySheet.getLastRow();
        const existingRows = lastRow > 1 ? buySheet.getRange(2, 1, lastRow - 1, buySheet.getLastColumn()).getValues() : [];
        
        data.candidates.forEach(c => {
          const tickerStr = String(c.ticker).trim();
          let existingIndex = -1;
          for (let i = 0; i < existingRows.length; i++) {
            const rowDateStr = String(existingRows[i][0]).substring(0, 10);
            const rowTickerStr = String(existingRows[i][1]).trim();
            if (rowDateStr === todayDateStr && rowTickerStr === tickerStr) {
              existingIndex = i;
              break;
            }
          }

          const newRowData = [today, c.ticker, c.name, c.priority, c.adx, c.prev_adx, c.minus_di, c.prev_minus_di, c.plus_di, c.rsi, c.close];

          if (existingIndex >= 0) {
            // Overwrite existing row on same date with latest timestamp & metrics
            buySheet.getRange(existingIndex + 2, 1, 1, newRowData.length).setValues([newRowData]);
          } else {
            // Append new row for new date or new stock candidate
            buySheet.appendRow(newRowData);
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
          today, s.ticker, s.name, s.adx, s.prev_adx, s.minus_di, s.prev_minus_di, s.plus_di, s.rsi, s.close, s.status
        ]);
        allSheet.getRange(2, 1, rows.length, 11).setValues(rows);
      }

      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", count: data.candidates ? data.candidates.length : 0 }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_sell_signals") {
      setupSheets();
      const sheet = ss.getSheetByName("Sell_Signals");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      const todayDateStr = today.substring(0, 10);

      if (data.signals && data.signals.length > 0 && sheet) {
        const lastRow = sheet.getLastRow();
        const existingData = lastRow > 1 ? sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues() : [];
        
        data.signals.forEach(s => {
          const tickerStr = String(s.ticker).trim();
          let existingIndex = -1;
          for (let i = 0; i < existingData.length; i++) {
            const rowDateStr = String(existingData[i][0]).substring(0, 10);
            const rowTickerStr = String(existingData[i][1]).trim();
            if (rowDateStr === todayDateStr && rowTickerStr === tickerStr) {
              existingIndex = i;
              break;
            }
          }

          const detailsText = Array.isArray(s.details) ? s.details.join(", ") : String(s.details || "");
          const newRowData = [today, s.ticker, s.name, s.buyPrice, s.currPrice, s.returnRate, s.adx, s.signalLevel, detailsText];

          if (existingIndex >= 0) {
            sheet.getRange(existingIndex + 2, 1, 1, newRowData.length).setValues([newRowData]);
          } else {
            sheet.appendRow(newRowData);
          }
        });
      }
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "trigger_screener") {
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
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", message: "수동 스크리닝이 깃허브 서버에서 시작되었습니다." }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "add_user_holding") {
      setupSheets();
      const sheet = ss.getSheetByName("User_Holdings");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd");
      sheet.appendRow([today, data.ticker, data.name, data.buyPrice, data.notes || ""]);
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "delete_user_holding") {
      const sheet = ss.getSheetByName("User_Holdings");
      if (sheet && sheet.getLastRow() > 1) {
        const dataRows = sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).getValues();
        for (let i = dataRows.length - 1; i >= 0; i--) {
          if (String(dataRows[i][1]) === String(data.ticker)) {
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
      rowObj[headers[j]] = rows[i][j];
    }
    data.push(rowObj);
  }
  return data;
}

/**
 * Setup 100% reliable daily automatic triggers inside Google Apps Script (10:05, 14:05, 15:45 KST)
 * Run setupDailyTriggers() once inside GAS Editor!
 */
function setupDailyTriggers() {
  const existingTriggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < existingTriggers.length; i++) {
    ScriptApp.deleteTrigger(existingTriggers[i]);
  }

  ScriptApp.newTrigger("triggerGitHubScreener")
    .timeBased()
    .atHour(10)
    .nearMinute(5)
    .everyDays(1)
    .create();

  ScriptApp.newTrigger("triggerGitHubScreener")
    .timeBased()
    .atHour(14)
    .nearMinute(5)
    .everyDays(1)
    .create();

  ScriptApp.newTrigger("triggerGitHubScreener")
    .timeBased()
    .atHour(15)
    .nearMinute(45)
    .everyDays(1)
    .create();

  Logger.log("✅ 구글 앱스 스크립트 정기 자동 트리거 설정 완료 (10:05, 14:05, 15:45 KST)!");
}

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
