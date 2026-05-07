/**
 * Google Apps Script for Cluster Label Validator
 * 
 * This script manages the Google Sheet backend for annotation storage and retrieval.
 * 
 * SETUP INSTRUCTIONS:
 * ===================
 * 1. Create a new Google Sheet: https://sheets.google.com
 * 2. Name it: "cluster_validator_annotations"
 * 3. Create columns with headers in Row 1:
 *    A: user_name
 *    B: cluster_cid
 *    C: appropriateness_rating
 *    D: follow_up_answers
 *    E: suggested_name
 *    F: notes
 *    G: timestamp
 * 4. Go to Extensions > Apps Script
 * 5. Replace the default code with this script
 * 6. Deploy as web app:
 *    - Click "Deploy" > "New deployment"
 *    - Type: "Web app"
 *    - Execute as: Your account
 *    - Who has access: "Anyone"
 *    - Copy the deployment URL
 * 7. Add to .streamlit/secrets.toml:
 *    GOOGLE_APPS_SCRIPT_URL = "your_deployment_url"
 *    GOOGLE_SHEET_READ_URL = "your_deployment_url"
 * 8. Restart your Streamlit app
 */

// Sheet name
const SHEET_NAME = "cluster_validator_annotations";

// Header row columns (1-indexed for Google Sheets API)
const HEADERS = {
  USER_NAME: 1,
  CLUSTER_CID: 2,
  APPROPRIATENESS_RATING: 3,
  FOLLOW_UP_ANSWERS: 4,
  SUGGESTED_NAME: 5,
  NOTES: 6,
  TIMESTAMP: 7
};

/**
 * Main handler for HTTP requests
 * Supports both GET (fetch progress) and POST (save annotation)
 */
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    return appendAnnotation(data);
  } catch (error) {
    return ContentService.createTextOutput(
      JSON.stringify({ success: false, error: error.toString() })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  try {
    const userName = e.parameter.user_name || e.parameter.annotator;
    return fetchUserProgress(userName);
  } catch (error) {
    return ContentService.createTextOutput(
      JSON.stringify({ success: false, error: error.toString() })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Append a single annotation to the sheet
 */
function appendAnnotation(data) {
  const sheet = SpreadsheetApp.getActiveSheet();
  
  // Ensure headers exist
  ensureHeaders(sheet);
  
  // Get current timestamp
  const timestamp = new Date().toISOString();
  
  // Prepare row data
  const newRow = [
    data.user_name || "",
    data.cluster_cid || "",
    data.appropriateness_rating || "",
    data.follow_up_answers || "{}",
    data.suggested_name || "",
    data.notes || "",
    timestamp
  ];
  
  // Append to sheet
  sheet.appendRow(newRow);
  
  return ContentService.createTextOutput(
    JSON.stringify({ 
      success: true, 
      message: "Annotation saved successfully",
      timestamp: timestamp
    })
  ).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Fetch all annotations for a specific user
 */
function fetchUserProgress(userName) {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  
  if (data.length <= 1) {
    // Only headers, no data
    return ContentService.createTextOutput(
      JSON.stringify({ success: true, rows: [] })
    ).setMimeType(ContentService.MimeType.JSON);
  }
  
  // Filter rows for this user (skip header row)
  const userRows = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (row[HEADERS.USER_NAME - 1] === userName) {
      userRows.push({
        user_name: row[HEADERS.USER_NAME - 1],
        cluster_cid: row[HEADERS.CLUSTER_CID - 1],
        appropriateness_rating: row[HEADERS.APPROPRIATENESS_RATING - 1],
        follow_up_answers: row[HEADERS.FOLLOW_UP_ANSWERS - 1],
        suggested_name: row[HEADERS.SUGGESTED_NAME - 1],
        notes: row[HEADERS.NOTES - 1],
        timestamp: row[HEADERS.TIMESTAMP - 1]
      });
    }
  }
  
  return ContentService.createTextOutput(
    JSON.stringify({ 
      success: true, 
      rows: userRows
    })
  ).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Ensure sheet has proper headers
 */
function ensureHeaders(sheet) {
  const firstRow = sheet.getRange(1, 1, 1, 7).getValues()[0];
  
  if (firstRow[0] !== "user_name") {
    sheet.insertRows(1);
    sheet.getRange(1, 1, 1, 7).setValues([[
      "user_name",
      "cluster_cid",
      "appropriateness_rating",
      "follow_up_answers",
      "suggested_name",
      "notes",
      "timestamp"
    ]]);
  }
}

/**
 * Optional: Admin function to view all annotations
 * Can be used for testing or monitoring
 */
function getAllAnnotations() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  
  if (data.length <= 1) {
    Logger.log("No annotations yet");
    return { success: true, count: 0, rows: [] };
  }
  
  // Skip header row
  const allRows = data.slice(1);
  Logger.log("Total annotations: " + allRows.length);
  
  // Log user summary
  const userSummary = {};
  for (let i = 0; i < allRows.length; i++) {
    const userName = allRows[i][HEADERS.USER_NAME - 1];
    userSummary[userName] = (userSummary[userName] || 0) + 1;
  }
  
  Logger.log("Annotations by user: " + JSON.stringify(userSummary));
  
  return { success: true, count: allRows.length, rows: allRows };
}
