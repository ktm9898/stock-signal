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
  allSheet.getRange("A1:Q1").setValues([["Date", "Ticker", "Name", "ADX", "Minus_DI", "Plus_DI", "RSI", "BB_Pct", "MACD", "MACD_Signal", "MACD_Osc", "Stoch_K", "Stoch_D", "Disparity20", "VolumeRatio", "ClosePrice", "Status"]]);
  allSheet.getRange("A1:Q1").setFontWeight("bold").setBackground("#f3e8ff");

  // 6. User Holdings Status Sheet Header Enforce
  let hStatusSheet = ss.getSheetByName("User_Holdings_Status") || ss.insertSheet("User_Holdings_Status");
  hStatusSheet.getRange("A1:N1").setValues([["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Prev_ADX", "Minus_DI", "Plus_DI", "RSI", "BB_Pct", "Status", "Details"]]);
  hStatusSheet.getRange("A1:N1").setFontWeight("bold").setBackground("#e0f2fe");

  // 7. KOSDAQ 150 All Metrics Sheet Header Enforce
  let kosdaqSheet = ss.getSheetByName("KOSDAQ150_All_Metrics") || ss.insertSheet("KOSDAQ150_All_Metrics");
  kosdaqSheet.getRange("A1:Q1").setValues([["Date", "Ticker", "Name", "ADX", "Minus_DI", "Plus_DI", "RSI", "BB_Pct", "MACD", "MACD_Signal", "MACD_Osc", "Stoch_K", "Stoch_D", "Disparity20", "VolumeRatio", "ClosePrice", "Status"]]);
  kosdaqSheet.getRange("A1:Q1").setFontWeight("bold").setBackground("#e0e7ff");

  // 8. Strategy Slots Sheet Header Enforce
  let slotsSheet = ss.getSheetByName("Strategy_Slots") || ss.insertSheet("Strategy_Slots");
  if (slotsSheet.getLastRow() === 0) {
    slotsSheet.getRange("A1:M1").setValues([["SlotID", "Name", "Memo", "Market", "Period", "StartDate", "EndDate", "StopLoss", "TakeProfit", "TradeAmount", "BuyRules", "SellRules", "UpdatedAt"]]);
    slotsSheet.getRange("A1:M1").setFontWeight("bold").setBackground("#dbeafe");
  }
}

function doGet(e) {
  const inputPin = e.parameter.pin ? String(e.parameter.pin).trim() : "";
  const authPin = getAuthPin();
  const action = e.parameter.action || "all";

  if (action === "get_strategy_slots") {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    setupSheets();
    let slotsSheet = ss.getSheetByName("Strategy_Slots");
    let slots = [];
    if (slotsSheet && slotsSheet.getLastRow() > 1) {
      const rows = slotsSheet.getRange(2, 1, slotsSheet.getLastRow() - 1, 13).getValues();
      slots = rows.map((r, idx) => ({
        id: r[0] || (idx + 1),
        name: r[1] || `전략 ${idx + 1}`,
        memo: r[2] || '',
        isEmpty: (r[1] && String(r[1]).includes('비어있음')) || !r[10],
        market: r[3] || 'ALL',
        period: r[4] || '5Y',
        startDate: r[5] || '',
        endDate: r[6] || '',
        stopLoss: r[7] !== '' ? Number(r[7]) : null,
        takeProfit: r[8] !== '' ? Number(r[8]) : null,
        tradeAmount: r[9] ? Number(r[9]) : 1000000,
        buyRules: r[10] ? JSON.parse(r[10]) : [],
        sellRules: r[11] ? JSON.parse(r[11]) : [],
        updatedAt: r[12] || '-'
      }));
    }
    
    if (slots.length < 10) {
      const jsonStr = PropertiesService.getScriptProperties().getProperty("STRATEGY_SLOTS_JSON");
      if (jsonStr) {
        try { slots = JSON.parse(jsonStr); } catch(err){}
      }
    }
    
    const activeSlotId = PropertiesService.getScriptProperties().getProperty("ACTIVE_STRATEGY_SLOT_ID") || "1";
    return ContentService.createTextOutput(JSON.stringify({ success: true, slots: slots, activeSlotId: parseInt(activeSlotId, 10) }))
      .setMimeType(ContentService.MimeType.JSON);
  }

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
  if (action === "all" || action === "all_metrics" || action === "kospi_metrics") result.allMetrics = getSheetData(ss.getSheetByName("KOSPI200_All_Metrics"));
  if (action === "all" || action === "kosdaq_metrics") result.kosdaqMetrics = getSheetData(ss.getSheetByName("KOSDAQ150_All_Metrics"));

  const activeSlotId = PropertiesService.getScriptProperties().getProperty("ACTIVE_STRATEGY_SLOT_ID") || "1";
  result.activeSlotId = parseInt(activeSlotId, 10);

  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const authPin = getAuthPin();

    if (data.action === "set_active_strategy_slot") {
      const slotId = String(data.slotId || "1");
      PropertiesService.getScriptProperties().setProperty("ACTIVE_STRATEGY_SLOT_ID", slotId);
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", activeSlotId: parseInt(slotId, 10) }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "save_strategy_slots") {
      setupSheets();
      const sheet = ss.getSheetByName("Strategy_Slots");
      if (data.slots && Array.isArray(data.slots) && sheet) {
        if (sheet.getLastRow() > 1) {
          sheet.getRange(2, 1, sheet.getLastRow() - 1, 13).clearContent();
        }
        const rows = data.slots.map(s => [
          s.id,
          s.name || `전략 ${s.id}`,
          s.memo || '',
          s.market || 'ALL',
          s.period || '5Y',
          s.startDate || '',
          s.endDate || '',
          s.stopLoss !== null && s.stopLoss !== undefined ? s.stopLoss : '',
          s.takeProfit !== null && s.takeProfit !== undefined ? s.takeProfit : '',
          s.tradeAmount || 1000000,
          JSON.stringify(s.buyRules || []),
          JSON.stringify(s.sellRules || []),
          s.updatedAt || '-'
        ]);
        sheet.getRange(2, 1, rows.length, 13).setValues(rows);
        PropertiesService.getScriptProperties().setProperty("STRATEGY_SLOTS_JSON", JSON.stringify(data.slots));
      }
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

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
          for (let i = existingRows.length - 1; i >= 0; i--) {
            const rowTickerStr = normalizeTicker(existingRows[i][1]);
            if (rowTickerStr === tickerStr) {
              const rowYMD = extractYMD(existingRows[i][0]);
              // 1) Same-day duplication check
              if (rowYMD === todayYMD) {
                exists = true;
                break;
              }
              // 2) Cross-day identical indicators/price check (same unupdated candle state)
              const rowAdx = Number(existingRows[i][4]);
              const rowMdi = Number(existingRows[i][6]);
              const rowRsi = Number(existingRows[i][9]);
              const rowClose = Number(existingRows[i][11]);
              const candAdx = Number(c.adx);
              const candMdi = Number(c.minus_di);
              const candRsi = Number(c.rsi);
              const candClose = Number(c.close);

              if (!isNaN(rowAdx) && !isNaN(candAdx) &&
                  Math.abs(rowAdx - candAdx) < 0.01 &&
                  Math.abs(rowMdi - candMdi) < 0.01 &&
                  Math.abs(rowRsi - candRsi) < 0.01 &&
                  rowClose === candClose) {
                exists = true;
                break;
              }
            }
          }

          // Keep the FIRST signal timestamp & metrics (do not duplicate)
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
        logSheet.appendRow([today, "SUCCESS", 350, data.candidates ? data.candidates.length : 0, "정상 완료"]);
      }

      // Record KOSPI 200 Metrics (Always Overwrite with Fresh Data)
      const kospiData = data.kospi_stocks || data.all_stocks;
      if (kospiData && kospiData.length > 0) {
        let allSheet = ss.getSheetByName("KOSPI200_All_Metrics");
        if (allSheet) {
          if (allSheet.getLastRow() > 1) {
            allSheet.getRange(2, 1, allSheet.getLastRow() - 1, 17).clearContent();
          }

          const rows = kospiData.map(s => [
            today, s.ticker, s.name, s.adx, s.minus_di, s.plus_di, s.rsi, 
            (s.b_band_pct !== undefined && s.b_band_pct !== null ? s.b_band_pct : '-'),
            (s.macd !== undefined && s.macd !== null ? s.macd : '-'),
            (s.macd_signal !== undefined && s.macd_signal !== null ? s.macd_signal : '-'),
            (s.macd_osc !== undefined && s.macd_osc !== null ? s.macd_osc : '-'),
            (s.stoch_k !== undefined && s.stoch_k !== null ? s.stoch_k : '-'),
            (s.stoch_d !== undefined && s.stoch_d !== null ? s.stoch_d : '-'),
            (s.disparity20 !== undefined && s.disparity20 !== null ? s.disparity20 : '-'),
            (s.volume_ratio !== undefined && s.volume_ratio !== null ? s.volume_ratio : '-'),
            s.close, s.status
          ]);
          
          allSheet.getRange(2, 1, rows.length, 17).setValues(rows);
        }
      }

      // Record KOSDAQ 150 Metrics (Always Overwrite with Fresh Data)
      if (data.kosdaq_stocks && data.kosdaq_stocks.length > 0) {
        let kosdaqSheet = ss.getSheetByName("KOSDAQ150_All_Metrics");
        if (kosdaqSheet) {
          if (kosdaqSheet.getLastRow() > 1) {
            kosdaqSheet.getRange(2, 1, kosdaqSheet.getLastRow() - 1, 17).clearContent();
          }

          const rows = data.kosdaq_stocks.map(s => [
            today, s.ticker, s.name, s.adx, s.minus_di, s.plus_di, s.rsi, 
            (s.b_band_pct !== undefined && s.b_band_pct !== null ? s.b_band_pct : '-'),
            (s.macd !== undefined && s.macd !== null ? s.macd : '-'),
            (s.macd_signal !== undefined && s.macd_signal !== null ? s.macd_signal : '-'),
            (s.macd_osc !== undefined && s.macd_osc !== null ? s.macd_osc : '-'),
            (s.stoch_k !== undefined && s.stoch_k !== null ? s.stoch_k : '-'),
            (s.stoch_d !== undefined && s.stoch_d !== null ? s.stoch_d : '-'),
            (s.disparity20 !== undefined && s.disparity20 !== null ? s.disparity20 : '-'),
            (s.volume_ratio !== undefined && s.volume_ratio !== null ? s.volume_ratio : '-'),
            s.close, s.status
          ]);
          
          kosdaqSheet.getRange(2, 1, rows.length, 17).setValues(rows);
        }
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
          for (let i = existingData.length - 1; i >= 0; i--) {
            const rowTickerStr = normalizeTicker(existingData[i][1]);
            if (rowTickerStr === tickerStr) {
              const rowYMD = extractYMD(existingData[i][0]);
              if (rowYMD === todayYMD) {
                exists = true;
                break;
              }
              const rowPrice = Number(existingData[i][4]);
              const rowAdx = Number(existingData[i][6]);
              const sPrice = Number(s.currPrice);
              const sAdx = Number(s.adx);
              if (!isNaN(rowPrice) && rowPrice === sPrice && !isNaN(rowAdx) && Math.abs(rowAdx - sAdx) < 0.01) {
                exists = true;
                break;
              }
            }
          }

          // Keep the FIRST sell alert timestamp
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

    if (data.action === "trigger_backtest_update") {
      const githubToken = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
      if (!githubToken) {
        return ContentService.createTextOutput(JSON.stringify({ 
          success: false, 
          status: "error", 
          message: "구글 앱스 스크립트에 GITHUB_TOKEN 이 설정되어 있지 않습니다. Script Properties에 GITHUB_TOKEN을 추가해주세요." 
        })).setMimeType(ContentService.MimeType.JSON);
      }

      const url = "https://api.github.com/repos/ktm9898/stock-signal/actions/workflows/update_backtest.yml/dispatches";
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
          return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", message: "5년 백테스트 데이터 갱신이 깃허브 클라우드에서 시작되었습니다." }))
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
