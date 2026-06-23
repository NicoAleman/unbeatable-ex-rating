/**
 * UNBEATABLE EX Rating — leaderboard submissions
 *
 * Setup:
 * 1. Open the leaderboard Google Sheet → Extensions → Apps Script
 * 2. Paste this file → Save
 * 3. Deploy → New deployment → Web app
 *    Execute as: Me | Who has access: Anyone
 * 4. Add the deployment URL to Streamlit secrets as pending_submission_url
 *
 * Behavior:
 * - New player names are added to the Approved tab immediately.
 * - Existing players can update only with a higher EX Rating (case-insensitive name match).
 * - EX Rating values are stored at full precision for sorting and tie-breaking.
 * - EX Rating cells use a 0.000 display format (three decimals shown, value unchanged).
 * - Every valid submission is also appended to the Pending tab as a log (duplicates allowed).
 */

const SPREADSHEET_ID = '16fpprBB4ynYxYFgoqnAlqmUCvXiEqRz-LgvivjvK_J0';
const APPROVED_TAB = 'Approved';
const PENDING_TAB = 'Pending';
const EX_RATING_DISPLAY_FORMAT = '0.000';

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const player = String(payload.player || '').trim();
    const exRating = Number(payload.ex_rating);
    const dateAdded =
      String(payload.date_added || '').trim() ||
      Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');

    if (!player) {
      return jsonResponse_({ success: false, error: 'Enter a player name.' });
    }
    if (Number.isNaN(exRating)) {
      return jsonResponse_({ success: false, error: 'Invalid EX rating.' });
    }

    const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = spreadsheet.getSheetByName(APPROVED_TAB);
    if (!sheet) {
      return jsonResponse_({ success: false, error: 'Approved sheet not found.' });
    }

    ensureHeaders_(sheet);
    const columns = getColumns_(sheet);
    const rows = sheet.getDataRange().getValues();
    const existing = findPlayerRow_(rows, columns, player);
    const submittedRating = exRating;
    let logResult = '';
    let response = null;

    if (existing === null) {
      appendPlayer_(sheet, columns, player, submittedRating, dateAdded);
      logResult = 'added';
      response = {
        success: true,
        status: 'added',
        message: 'Added to the leaderboard!',
      };
    } else if (submittedRating <= existing.rating) {
      logResult = 'rejected';
      response = {
        success: false,
        error:
          'Your submitted rating (' +
          formatRating_(submittedRating) +
          ') must be higher than your current leaderboard rating (' +
          formatRating_(existing.rating) +
          ').',
      };
    } else {
      const ratingCell = sheet.getRange(existing.rowIndex + 1, columns.rating + 1);
      ratingCell.setValue(submittedRating);
      applyExRatingDisplayFormat_(ratingCell);
      if (columns.date >= 0) {
        sheet.getRange(existing.rowIndex + 1, columns.date + 1).setValue(dateAdded);
      }
      logResult = 'updated';
      response = {
        success: true,
        status: 'updated',
        message: 'Your leaderboard rating has been updated!',
      };
    }

    appendSubmissionLog_(spreadsheet, player, submittedRating, dateAdded, logResult);
    return jsonResponse_(response);
  } catch (error) {
    return jsonResponse_({ success: false, error: String(error.message || error) });
  }
}

function doGet() {
  return jsonResponse_({ ok: true, service: 'unbeatable-ex-rating-submissions' });
}

function jsonResponse_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(
    ContentService.MimeType.JSON
  );
}

function ensureHeaders_(sheet) {
  if (sheet.getLastRow() > 0) {
    return;
  }
  sheet.appendRow(['Player', 'EX Rating', 'Last Updated']);
}

function getColumns_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const normalized = headers.map(function (header) {
    return String(header).trim().toLowerCase();
  });

  const player = normalized.indexOf('player');
  let rating = normalized.indexOf('ex rating');
  if (rating < 0) {
    rating = normalized.findIndex(function (header) {
      return header.indexOf('ex') >= 0 && header.indexOf('rating') >= 0;
    });
  }
  let date = normalized.indexOf('last updated');
  if (date < 0) {
    date = normalized.indexOf('date added');
  }
  if (date < 0) {
    date = normalized.indexOf('date');
  }

  if (player < 0 || rating < 0) {
    throw new Error('Approved sheet must have Player and EX Rating columns.');
  }

  return { player: player, rating: rating, date: date };
}

function findPlayerRow_(rows, columns, playerName) {
  const key = playerName.toLowerCase();
  for (let i = 1; i < rows.length; i++) {
    const name = String(rows[i][columns.player] || '').trim();
    if (name.toLowerCase() === key) {
      return {
        rowIndex: i,
        rating: Number(rows[i][columns.rating]),
      };
    }
  }
  return null;
}

function appendPlayer_(sheet, columns, player, rating, dateAdded) {
  const row = [];
  row[columns.player] = player;
  row[columns.rating] = rating;
  if (columns.date >= 0) {
    row[columns.date] = dateAdded;
  }

  const width = sheet.getLastColumn();
  const normalized = [];
  for (let i = 0; i < width; i++) {
    normalized[i] = row[i] !== undefined ? row[i] : '';
  }
  sheet.appendRow(normalized);
  applyExRatingDisplayFormat_(sheet.getRange(sheet.getLastRow(), columns.rating + 1));
}

function ensurePendingHeaders_(sheet) {
  if (sheet.getLastRow() > 0) {
    return;
  }
  sheet.appendRow(['Player', 'EX Rating', 'Date Added', 'Result']);
}

function appendSubmissionLog_(spreadsheet, player, rating, dateAdded, result) {
  const pendingSheet = spreadsheet.getSheetByName(PENDING_TAB);
  if (!pendingSheet) {
    return;
  }

  ensurePendingHeaders_(pendingSheet);
  pendingSheet.appendRow([player, rating, dateAdded, result]);
  applyExRatingDisplayFormat_(pendingSheet.getRange(pendingSheet.getLastRow(), 2));
}

function applyExRatingDisplayFormat_(range) {
  range.setNumberFormat(EX_RATING_DISPLAY_FORMAT);
}

function formatRating_(value) {
  return Number(value).toFixed(3);
}
