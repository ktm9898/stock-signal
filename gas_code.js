function getAuthPin() {
  try {
    const prop = PropertiesService.getScriptProperties().getProperty("AUTH_PIN");
    if (prop && String(prop).trim() !== "") {
      return String(prop).trim();
    }
  } catch (err) {}
  return "";
}

function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // 1. Buy_Candidates Sheet
  let buySheet = ss.getSheetByName("Buy_Candidates");
  if (!buySheet) {
    buySheet = ss.insertSheet("Buy_Candidates");
  }
  if (buySheet.getLastRow() === 0) {
    buySheet.appendRow(["Date", "Ticker", "Name", "Tier", "ADX", "Minus_DI", "Plus_DI", "RSI", "ClosePrice"]);
    buySheet.getRange("A1:I1").setFontWeight("bold").setBackground("#e0f2fe");
  }

  // 2. User_Holdings Sheet
  let holdingsSheet = ss.getSheetByName("User_Holdings");
  if (!holdingsSheet) {
    holdingsSheet = ss.insertSheet("User_Holdings");
  }
  if (holdingsSheet.getLastRow() === 0) {
    holdingsSheet.appendRow(["DateAdded", "Ticker", "Name", "BuyPrice", "Notes"]);
    holdingsSheet.getRange("A1:E1").setFontWeight("bold").setBackground("#fef3c7");
  }

  // 3. Sell_Signals Sheet
  let sellSheet = ss.getSheetByName("Sell_Signals");
  if (!sellSheet) {
    sellSheet = ss.insertSheet("Sell_Signals");
  }
  if (sellSheet.getLastRow() === 0) {
    sellSheet.appendRow(["Date", "Ticker", "Name", "BuyPrice", "CurrPrice", "ReturnRate", "ADX", "Status", "Details"]);
    sellSheet.getRange("A1:I1").setFontWeight("bold").setBackground("#fee2e2");
  }
}

// REST API GET Endpoint (Serve JSON data to Web App with PIN check)
function doGet(e) {
  const inputPin = e.parameter.pin ? String(e.parameter.pin).trim() : "";
  const authPin = getAuthPin();

  if (inputPin !== authPin) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Unauthorized: Invalid PIN" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const action = e.parameter.action || "all";

  let result = { status: "success" };

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

// REST API POST Endpoint (Receive Python Screener data & Web App registrations with PIN check)
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const authPin = getAuthPin();

    // Verify PIN for all user actions
    const inputPin = data.pin ? String(data.pin).trim() : "";
    if (inputPin !== authPin && data.action !== "update_buy_candidates") {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Unauthorized: Invalid PIN" }));
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
      return ContentService.createTextOutput(JSON.stringify({ status: "success", count: data.candidates.length }));
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
      return ContentService.createTextOutput(JSON.stringify({ status: "success" }));
    }

    if (data.action === "add_user_holding") {
      const sheet = ss.getSheetByName("User_Holdings");
      const today = Utilities.formatDate(new Date(), "GMT+9", "yyyy-MM-dd");
      sheet.appendRow([today, data.ticker, data.name, data.buyPrice, data.notes || ""]);
      return ContentService.createTextOutput(JSON.stringify({ status: "success" }));
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "Unknown action" }));
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.toString() }));
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

