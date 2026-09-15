/*
 * Computer Prachi - Tutor Registration storage backend
 * Google Apps Script Web App
 *
 * 1) Google Drive में नई Google Sheet बनाएं.
 * 2) Extensions > Apps Script खोलें.
 * 3) इस code को Code.gs में paste करें.
 * 4) SHEET_ID में Sheet URL के /d/ और /edit के बीच वाला ID डालें.
 * 5) Deploy > New deployment > Web app
 *    Execute as: Me
 *    Who has access: Anyone
 * 6) Web app URL को tutor-registration.html में CP_TUTOR_API में डालें.
 */
const SHEET_ID = 'PASTE_GOOGLE_SHEET_ID_HERE';
const SHEET_NAME = 'Tutor Registrations';

function setupSheet_() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(['Registration ID','Timestamp','Name','Mobile','WhatsApp','Email','Gender','Qualification','Subjects','Classes','Board','Experience','Mode','City','Area','Expected Fee','Available Time','About','Payment Status','Verification Status']);
  }
  return sh;
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents || '{}');
    const required = ['name','mobile','qualification','subjects','city'];
    required.forEach(k => { if (!String(data[k] || '').trim()) throw new Error('Required field missing: ' + k); });
    if (!/^\\d{10}$/.test(String(data.mobile).trim())) throw new Error('Invalid mobile number');

    const sh = setupSheet_();
    const id = 'CP-T' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMddHHmmss') + Math.floor(Math.random()*90+10);
    sh.appendRow([
      id,new Date(),data.name,data.mobile,data.whatsapp || '',data.email || '',data.gender || '',data.qualification,
      data.subjects,data.classes || '',data.board || '',data.experience || '',data.mode || '',data.city,data.area || '',
      data.tuitionFee || '',data.time || '',data.about || '','Pending Payment','Pending Review'
    ]);
    return json_({ok:true,registrationId:id});
  } catch (err) {
    return json_({ok:false,error:err.message});
  }
}

function doGet() {
  return json_({ok:true,service:'Computer Prachi Tutor Registration'});
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
