// Google Apps Script Code for StockSignal Project

function getAuthPin() {
  const pin = PropertiesService.getScriptProperties().getProperty("AUTH_PIN");
  return pin ? String(pin).trim() : "";
}

function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let buySheet = ss.getSheetByName("Buy_Candidates");
  if (!buySheet) buySheet = ss.insertSheet("Buy_Candidates");
  if (buySheet.getLastRow() === 0) {
    buySheet.appendRow(["Date", "Ticker", "Name", "Tier", "ADX", "Minus_DI", "Plus_DI", "RSI", "ClosePrice"]);
    buySheet.getRange("A1:I1").setFontWeight("bold").setBackground("#e0f2fe");
  }

  let holdingsSheet = ss.getSheetByName("User_Holdings");
  if (!holdingsSheet) holdingsSheet = ss.insertSheet("User_Holdings");
  if (holdingsSheet.getLastRow() === 0) {
    holdingsSheet.appendRow(["DateAdded", "Ticker", "Name", "BuyPrice", "Notes"]);
    holdingsSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#fef3c7");
  }

  let sellSheet = ss.getSheetByName("Sell_Signals");
  if (!sellSheet) sellSheet = ss.insertSheet("Sell_Signals");
  if (sellSheet.getLastRow() === 0) {
    sellSheet.appendRow(["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Status", "Details"]);
    sellSheet.getRange("A1:I1").setFontWeight("bold").setBackground("#fee2e2");
  }
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

  if (action === "all" || action === "buy") {
    result.buyCandidates = getSheetData(ss.getSheetByName("Buy_Candidates"));
  }
  if (action === "all" || action === "holdings") {
    result.userHoldings = getSheetData(ss.getSheetByName("User_Holdings"));
  }
  if (action === "all" || action === "sell") {
    result.sellSignals = getSheetData(ss.getSheetByName("Sell_Signals"));
  }

  return ContentService.createTextOutput(JSON.stringify(result))
    .setMimeType(ContentService.MimeType.JSON);
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
      const sheet = ss.getSheetByName("Buy_Candidates");
      if (sheet.getLastRow() > 1) {
        sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
      }
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      data.candidates.forEach(c => {
        sheet.appendRow([today, c.ticker, c.name, c.priority, c.adx, c.minus_di, c.plus_di, c.rsi, c.close]);
      });
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success", count: data.candidates.length }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "update_sell_signals") {
      const sheet = ss.getSheetByName("Sell_Signals");
      if (sheet.getLastRow() > 1) {
        sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
      }
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd HH:mm");
      data.signals.forEach(s => {
        sheet.appendRow([today, s.ticker, s.name, s.buyPrice, s.currPrice, s.returnRate, s.adx, s.signalLevel, s.details.join(", ")]);
      });
      return ContentService.createTextOutput(JSON.stringify({ success: true, status: "success" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (data.action === "add_user_holding") {
      const sheet = ss.getSheetByName("User_Holdings");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd");
      sheet.appendRow([today, data.ticker, data.name, data.buyPrice, data.notes || ""]);
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

