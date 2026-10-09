// Paste this into your Google Sheet: Extensions -> Apps Script (replace ALL the old code)
// Keep the SAME secret word you used before.
const SECRET = "change-this-to-your-own-secret";

const HEADERS = ["Logged at", "Email date", "From", "Subject", "Category", "Urgency",
                 "Summary", "Draft reply", "Status", "Message ID", "Meeting"];

function getSheet() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName("Log") || book.insertSheet("Log");
  sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight("bold");
  sheet.setFrozenRows(1);
  return sheet;
}

// Stops email text that starts with = + - @ being treated as a spreadsheet formula
function safe(value) {
  const text = String(value || "");
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function reply(text) {
  return ContentService.createTextOutput(text);
}

// "2026-10-13 14:00" -> a Date in this script's time zone (Project Settings)
function parseLocal(text) {
  const [day, time] = text.split(" ");
  const [y, mo, d] = day.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  return new Date(y, mo - 1, d, h, mi);
}

// You CAN click Run on this one. It checks the sheet AND asks for Calendar permission.
function testSetup() {
  getSheet();
  const events = CalendarApp.getDefaultCalendar().getEventsForDay(new Date());
  Logger.log("Setup OK. Log tab ready. Calendar connected: " + events.length + " event(s) today.");
}

// Don't click Run on doPost. It only runs when your Python code sends data.
function doPost(e) {
  if (!e || !e.postData) return reply("No data received.");
  const data = JSON.parse(e.postData.contents);
  if (data.secret !== SECRET) return reply("forbidden");

  // ---- Calendar: is that time free? ----
  if (data.action === "check_free") {
    const start = parseLocal(data.start);
    const end = new Date(start.getTime() + data.minutes * 60000);
    const busy = CalendarApp.getDefaultCalendar().getEvents(start, end).length > 0;
    return reply(busy ? "busy" : "free");
  }

  // ---- Calendar: create the meeting ----
  if (data.action === "create_event") {
    const start = parseLocal(data.start);
    const end = new Date(start.getTime() + data.minutes * 60000);
    const options = { description: data.description || "" };
    if (data.guest) {
      options.guests = data.guest;
      options.sendInvites = true;
    }
    CalendarApp.getDefaultCalendar().createEvent(data.title, start, end, options);
    return reply("ok");
  }

  const sheet = getSheet();

  // ---- Update the Status of an email that's already logged ----
  if (data.action === "update_status") {
    const last = sheet.getLastRow();
    if (last < 2) return reply("not found");
    const ids = sheet.getRange(2, 10, last - 1, 1).getValues();
    for (let i = ids.length - 1; i >= 0; i--) {
      if (ids[i][0] === data.message_id) {
        sheet.getRange(i + 2, 9).setValue(data.status);
        return reply("ok");
      }
    }
    return reply("not found");
  }

  // ---- Otherwise, add a new row ----
  const status = data.draft_reply ? "Waiting for approval" : "No reply needed";
  sheet.appendRow([new Date(), data.date, safe(data.sender), safe(data.subject), data.category,
                   data.urgency, safe(data.summary), safe(data.draft_reply), status,
                   data.message_id, data.meeting || ""]);
  return reply("ok");
}
