/*
 * Computer Prachi - Tutor Registration + Student Tutor Profile Unlock
 * Google Apps Script Web App
 */
const SHEET_NAME = "Sheet1";
const UNLOCK_SHEET_NAME = "Tutor Profile Unlocks";
const RAZORPAY_API = "https://api.razorpay.com/v1/payment_links";
const CALLBACK_URL = "https://script.google.com/macros/s/AKfycbyMyzWHtyHedM6uLdVPmsGDcm_AjlebLYd_QP24HOtbLfV-8MVgpRg1P-VPjUr9YDgFyg/exec";

function doGet(e) {
  const p = e && e.parameter ? e.parameter : {};
  if (p.razorpay_payment_link_id) return handlePaymentCallback(p);

  if (p.action === "approved_tutors") {
    return jsonResponse({success:true, tutors:getApprovedTutors()});
  }

  return ContentService.createTextOutput(
    "Computer Prachi Tutor Registration API is working."
  ).setMimeType(ContentService.MimeType.TEXT);
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData && e.postData.contents ? e.postData.contents : "{}");

    if (data.requestType === "student_profile_unlock") {
      return createProfileUnlock(data);
    }

    if (data.requestType === "student_enquiry") {
      return saveStudentEnquiry(data);
    }

    return saveTutorRegistration(data);
  } catch (error) {
    return jsonResponse({success:false,error:error.message});
  }
}

function getTutorSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.getSheetByName("Tutor Registrations");
  if (!sheet) throw new Error("Tutor registration sheet नहीं मिली।");
  return sheet;
}

function saveTutorRegistration(data) {
  const sheet = getTutorSheet();
  const required = ["name","mobile","qualification","subjects","city"];
  required.forEach(function(k) {
    if (!String(data[k] || "").trim()) throw new Error("Required field missing: " + k);
  });
  if (!/^\d{10}$/.test(String(data.mobile).trim())) {
    throw new Error("Invalid mobile number");
  }

  ensureTutorHeaders(sheet);

  const id = createRegistrationId();
  sheet.appendRow([
    id, new Date(), data.name || "", data.mobile || "", data.whatsapp || "",
    data.email || "", data.gender || "", data.qualification || "",
    data.subjects || "", data.classes || "", data.board || "",
    data.experience || "", data.mode || "", data.city || "", data.area || "",
    data.tuitionFee || "", data.time || "", data.about || "",
    "Pending", "Pending", "", ""
  ]);

  const row = sheet.getLastRow();
  const payment = createRazorpayPaymentLink(
    id,
    data,
    "Computer Prachi Tutor Registration",
    "CP-T-" + id
  );

  setCellByHeader(sheet, row, "Razorpay Payment Link ID", payment.id);

  return jsonResponse({
    success:true,
    registrationId:id,
    paymentUrl:payment.short_url,
    paymentLinkId:payment.id
  });
}

function ensureTutorHeaders(sheet) {
  const requiredHeaders = [
    "Registration ID","Date/Time","Name","Mobile","WhatsApp","Email",
    "Gender","Qualification","Subjects","Classes","Board",
    "Teaching Experience","Teaching Mode","City/District","Area/Locality",
    "Expected Tuition Fee","Available Time","About / Teaching Profile",
    "Payment Status","Verification Status","Razorpay Payment Link ID","Payment ID"
  ];

  const lastColumn = sheet.getLastColumn();
  if (sheet.getLastRow() === 0 || lastColumn === 0) {
    sheet.getRange(1,1,1,requiredHeaders.length).setValues([requiredHeaders]);
    return;
  }

  const existing = sheet.getRange(1,1,1,lastColumn).getValues()[0];
  requiredHeaders.forEach(function(h) {
    if (existing.indexOf(h) === -1) {
      sheet.getRange(1,sheet.getLastColumn()+1).setValue(h);
      existing.push(h);
    }
  });
}

function createRegistrationId() {
  return "CP-T-" + Utilities.formatDate(
    new Date(), Session.getScriptTimeZone(), "yyyyMMdd-HHmmss"
  );
}

function getApprovedTutors() {
  const sheet = getTutorSheet();
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];

  const headers = values[0];
  const out = [];

  for (let i=1; i<values.length; i++) {
    const row = values[i];
    const status = String(getByHeader(headers,row,"Verification Status") || "").trim().toLowerCase();
    const payment = String(getByHeader(headers,row,"Payment Status") || "").trim().toLowerCase();

    if (status !== "approved" || payment !== "paid") continue;

    out.push({
      registrationId:String(getByHeader(headers,row,"Registration ID") || ""),
      name:String(getByHeader(headers,row,"Name") || ""),
      qualification:String(getByHeader(headers,row,"Qualification") || ""),
      subjects:String(getByHeader(headers,row,"Subjects") || ""),
      classes:String(getByHeader(headers,row,"Classes") || ""),
      board:String(getByHeader(headers,row,"Board") || ""),
      experience:String(getByHeader(headers,row,"Teaching Experience") || ""),
      mode:String(getByHeader(headers,row,"Teaching Mode") || ""),
      city:String(getByHeader(headers,row,"City/District") || ""),
      area:String(getByHeader(headers,row,"Area/Locality") || "")
    });
  }
  return out;
}

function createProfileUnlock(data) {
  const tutorId = String(data.tutorRegistrationId || "").trim();
  if (!tutorId) throw new Error("Tutor Registration ID required.");

  const tutor = findTutorById(tutorId);
  if (!tutor) throw new Error("Tutor profile नहीं मिली।");
  if (String(tutor.verificationStatus).toLowerCase() !== "approved") {
    throw new Error("यह tutor profile अभी approved नहीं है।");
  }
  if (String(tutor.paymentStatus).toLowerCase() !== "paid") {
    throw new Error("Tutor registration payment अभी confirmed नहीं है।");
  }

  const unlockSheet = getUnlockSheet();
  const unlockId = "CP-U-" + Utilities.formatDate(
    new Date(), Session.getScriptTimeZone(), "yyyyMMdd-HHmmss"
  ) + Math.floor(Math.random()*90+10);

  unlockSheet.appendRow([
    unlockId, new Date(), tutorId, tutor.name,
    data.studentName || "", data.mobile || "", data.email || "",
    "Pending", "", ""
  ]);

  const payment = createRazorpayPaymentLink(
    unlockId,
    {
      name: data.studentName || "Student",
      mobile: data.mobile || "",
      email: data.email || ""
    },
    "Computer Prachi Teacher Profile Unlock - ₹10",
    "CP-U-" + unlockId
  );

  const row = unlockSheet.getLastRow();
  setCellByHeader(unlockSheet,row,"Razorpay Payment Link ID",payment.id);

  return jsonResponse({
    success:true,
    unlockId:unlockId,
    paymentUrl:payment.short_url,
    paymentLinkId:payment.id
  });
}

function getUnlockSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(UNLOCK_SHEET_NAME);
  if (!sh) sh = ss.insertSheet(UNLOCK_SHEET_NAME);

  const headers = [
    "Unlock ID","Date/Time","Tutor Registration ID","Tutor Name",
    "Student Name","Student Mobile","Student Email",
    "Payment Status","Razorpay Payment Link ID","Payment ID"
  ];

  if (sh.getLastRow() === 0) {
    sh.getRange(1,1,1,headers.length).setValues([headers]);
  } else {
    const existing = sh.getRange(1,1,1,sh.getLastColumn()).getValues()[0];
    headers.forEach(function(h) {
      if (existing.indexOf(h) === -1) {
        sh.getRange(1,sh.getLastColumn()+1).setValue(h);
        existing.push(h);
      }
    });
  }
  return sh;
}

function findTutorById(id) {
  const sheet = getTutorSheet();
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return null;

  const headers = values[0];
  for (let i=1; i<values.length; i++) {
    if (String(getByHeader(headers,values[i],"Registration ID") || "") === id) {
      return {
        row:i+1,
        registrationId:String(getByHeader(headers,values[i],"Registration ID") || ""),
        dateTime:getByHeader(headers,values[i],"Date/Time"),
        name:String(getByHeader(headers,values[i],"Name") || ""),
        mobile:String(getByHeader(headers,values[i],"Mobile") || ""),
        whatsapp:String(getByHeader(headers,values[i],"WhatsApp") || ""),
        email:String(getByHeader(headers,values[i],"Email") || ""),
        gender:String(getByHeader(headers,values[i],"Gender") || ""),
        qualification:String(getByHeader(headers,values[i],"Qualification") || ""),
        subjects:String(getByHeader(headers,values[i],"Subjects") || ""),
        classes:String(getByHeader(headers,values[i],"Classes") || ""),
        board:String(getByHeader(headers,values[i],"Board") || ""),
        experience:String(getByHeader(headers,values[i],"Teaching Experience") || ""),
        mode:String(getByHeader(headers,values[i],"Teaching Mode") || ""),
        city:String(getByHeader(headers,values[i],"City/District") || ""),
        area:String(getByHeader(headers,values[i],"Area/Locality") || ""),
        tuitionFee:String(getByHeader(headers,values[i],"Expected Tuition Fee") || ""),
        time:String(getByHeader(headers,values[i],"Available Time") || ""),
        about:String(getByHeader(headers,values[i],"About / Teaching Profile") || ""),
        paymentStatus:String(getByHeader(headers,values[i],"Payment Status") || ""),
        verificationStatus:String(getByHeader(headers,values[i],"Verification Status") || "")
      };
    }
  }
  return null;
}

function handlePaymentCallback(p) {
  try {
    const paymentLinkId = p.razorpay_payment_link_id || "";
    const paymentId = p.razorpay_payment_id || "";
    const referenceId = p.razorpay_payment_link_reference_id || "";
    const paymentStatus = p.razorpay_payment_link_status || "";
    const signature = p.razorpay_signature || "";

    if (!paymentLinkId || !paymentId || !referenceId || !signature) {
      return callbackPage("Payment information incomplete.", false);
    }

    const secret = PropertiesService.getScriptProperties().getProperty("RAZORPAY_KEY_SECRET");
    if (!secret) return callbackPage("Payment verification configuration missing.", false);

    const payload = paymentLinkId + "|" + referenceId + "|" + paymentStatus + "|" + paymentId;
    const expected = bytesToHex(Utilities.computeHmacSha256Signature(payload, secret));

    if (!constantTimeEquals(expected, signature)) {
      return callbackPage("Payment verification failed.", false);
    }

    const paymentLink = fetchPaymentLink(paymentLinkId);
    if (paymentLink.status !== "paid") {
      return callbackPage("Payment अभी confirmed नहीं हुआ है.", false);
    }

    // IMPORTANT: Tutor Registration and Teacher Profile Unlock are separate payments.
    // CP-U- = profile unlock; CP-T- = tutor registration.
    if (referenceId.indexOf("CP-U-") === 0) {
      return handleProfileUnlockPaid(referenceId, paymentLinkId, paymentId);
    }

    if (referenceId.indexOf("CP-T-") === 0) {
      return handleTutorRegistrationPaid(referenceId, paymentLinkId, paymentId);
    }

    return callbackPage("Unknown payment reference.", false);
  } catch (error) {
    return callbackPage("Payment verification error: " + error.message, false);
  }
}

function handleTutorRegistrationPaid(referenceId, paymentLinkId, paymentId) {
  const sheet = getTutorSheet();
  const row = findRowByHeader(sheet, "Registration ID", referenceId);
  if (!row) return callbackPage("Registration ID नहीं मिली.", false);

  setCellByHeader(sheet, row, "Payment Status", "Paid");
  setCellByHeader(sheet, row, "Payment ID", paymentId);
  setCellByHeader(sheet, row, "Razorpay Payment Link ID", paymentLinkId);

  const tutor = findTutorById(referenceId);
  if (!tutor) return callbackPage("Tutor registration record नहीं मिला.", false);

  return tutorRegistrationReceiptPage(referenceId, tutor, paymentId, new Date());
}

function handleProfileUnlockPaid(referenceId, paymentLinkId, paymentId) {
  const unlockSheet = getUnlockSheet();
  const unlockRow = findRowByHeader(unlockSheet, "Unlock ID", referenceId);
  if (!unlockRow) return callbackPage("Profile unlock record नहीं मिला.", false);

  setCellByHeader(unlockSheet, unlockRow, "Payment Status", "Paid");
  setCellByHeader(unlockSheet, unlockRow, "Payment ID", paymentId);
  setCellByHeader(unlockSheet, unlockRow, "Razorpay Payment Link ID", paymentLinkId);

  const tutorId = String(getCellByHeader(unlockSheet, unlockRow, "Tutor Registration ID") || "");
  const tutor = findTutorById(tutorId);
  if (!tutor) return callbackPage("Tutor profile नहीं मिली.", false);

  return profileUnlockReceiptPage(referenceId, tutor, paymentId, new Date());
}

function tutorRegistrationReceiptPage(referenceId, tutor, paymentId, paymentDate) {
  const dateText = paymentDate ? new Date(paymentDate).toLocaleString("en-IN") : "-";
  const title = "Computer Prachi - Payment Successful";
  const html = "<!doctype html><html><head>" +
    "<meta name='viewport' content='width=device-width,initial-scale=1'>" +
    "<title>Computer Prachi - Tutor Registration Receipt - " + escapeHtml(referenceId) + "</title>" +
    "<style>body{font-family:Arial,sans-serif;text-align:center;padding:30px;background:#f5f7fb}.box{max-width:560px;margin:auto;background:white;padding:30px;border-radius:16px;box-shadow:0 5px 25px rgba(0,0,0,.1)}.receipt{text-align:left;margin-top:20px;padding:20px;border:1px solid #ddd;border-radius:12px}.line{border-top:1px solid #ddd;margin:18px 0}button{display:block;width:100%;padding:13px;margin-top:12px;border:0;border-radius:8px;background:#1677ff;color:white;font-size:16px;cursor:pointer}button.back{background:#198754}@media print{button{display:none}.box{box-shadow:none;border:0}}</style>" +
    "</head><body><div class='box'><div style='font-size:55px'>✅</div><h1>" + title + "</h1>" +
    "<div class='receipt'><h2 style='text-align:center'>Computer Prachi</h2><div class='line'></div>" +
    "<p><b>Registration ID:</b><br>" + escapeHtml(referenceId) + "</p>" +
    "<p><b>Name:</b><br>" + escapeHtml(tutor.name) + "</p>" +
    "<p><b>Registration Date/Time:</b><br>" + escapeHtml(dateText) + "</p>" +
    "<p><b>Amount Paid:</b><br>₹10</p>" +
    "<p><b>Payment ID:</b><br>" + escapeHtml(paymentId) + "</p><div class='line'></div>" +
    "<button onclick='window.print()'>🖨️ Print / Save as PDF</button>" +
    "<button class='back' onclick=\"window.location.href='https://computerprachi.online/tutor-registration.html'\">🔙 Back to Teacher Registration</button>" +
    "</div></div></body></html>";
  return HtmlService.createHtmlOutput(html);
}

function profileUnlockReceiptPage(referenceId, tutor, paymentId, paymentDate) {
  const dateText = paymentDate ? new Date(paymentDate).toLocaleString("en-IN") : "-";
  const title = "Computer Prachi - Teacher Profile Unlocked";
  const receipt = "<div class='receipt'><h2>Computer Prachi</h2><p><b>Teacher Profile Unlock – ₹10</b></p>" +
    "<p><b>Teacher Registration ID:</b><br>" + escapeHtml(tutor.registrationId) + "</p>" +
    "<p><b>Teacher Name:</b><br>" + escapeHtml(tutor.name) + "</p>" +
    "<p><b>Payment Date & Time:</b><br>" + escapeHtml(dateText) + "</p>" +
    "<p><b>Amount Paid:</b><br>₹10</p>" +
    "<p><b>Razorpay Payment ID:</b><br>" + escapeHtml(paymentId) + "</p>" +
    "<p><b>Payment Status:</b><br>Successful</p>" +
    "<button onclick='window.print()'>🖨️ Print / Save as PDF</button>" +
    "<button class='back' onclick=\"window.location.href='https://computerprachi.online/find-tutor.html'\">🔙 Back to Teacher Profile</button></div>";

  const profile = "<div class='profile'><h2>👨‍🏫 Full Teacher Profile</h2>" +
    row("Teacher Name", tutor.name) + row("Registration ID", tutor.registrationId) +
    row("Mobile", tutor.mobile) + row("WhatsApp", tutor.whatsapp) + row("Email", tutor.email) +
    row("Gender", tutor.gender) + row("Qualification", tutor.qualification) + row("Subjects", tutor.subjects) +
    row("Classes", tutor.classes) + row("Board", tutor.board) + row("Teaching Experience", tutor.experience) +
    row("Teaching Mode", tutor.mode) + row("City / District", tutor.city) + row("Area / Locality", tutor.area) +
    row("Expected Tuition Fee", tutor.tuitionFee) + row("Available Time", tutor.time) +
    row("About / Teaching Profile", tutor.about) + "</div>";

  return HtmlService.createHtmlOutput(
    "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>" +
    "<title>" + escapeHtml(title) + " - " + escapeHtml(tutor.registrationId) + "</title><style>" +
    "body{font-family:Arial,sans-serif;background:#f4f7fb;margin:0;padding:22px;color:#222}.box{max-width:720px;margin:auto;background:#fff;padding:24px;border-radius:16px;box-shadow:0 5px 25px rgba(0,0,0,.1)}.icon{font-size:50px;text-align:center}.receipt,.profile{margin-top:18px;padding:18px;border:1px solid #d8dee8;border-radius:12px}.receipt{background:#f4fff6}.receipt h2,.profile h2{text-align:center;color:#102d69;margin-top:0}.row{padding:8px 0;border-bottom:1px solid #eee;line-height:1.5}.row:last-child{border-bottom:0}button{display:block;width:100%;padding:12px;margin-top:12px;border:0;border-radius:8px;background:#1677ff;color:#fff;font-size:16px;cursor:pointer}button.back{background:#198754}@media print{body{background:#fff}.box{box-shadow:none}.receipt button{display:none}}</style></head><body><div class='box'>" +
    "<div class='icon'>✅</div><h1 style='text-align:center'>" + escapeHtml(title) + "</h1>" +
    "<p style='text-align:center;font-size:17px'>₹10 payment successfully received. Teacher profile unlocked.</p>" +
    receipt + profile + "</div></body></html>"
  );
}

function callbackPage(message, success) {
  const title = success ? "Payment Successful" : "Payment Verification";
  const icon = success ? "✅" : "⚠️";
  const safeMessage = escapeHtml(message || "");
  const html = "<!doctype html><html><head>" +
    "<meta name='viewport' content='width=device-width,initial-scale=1'>" +
    "<title>Computer Prachi - " + title + "</title>" +
    "<style>body{font-family:Arial,sans-serif;text-align:center;padding:30px;background:#f5f7fb}.box{max-width:560px;margin:auto;background:#fff;padding:30px;border-radius:16px;box-shadow:0 5px 25px rgba(0,0,0,.1)}.icon{font-size:55px}p{font-size:17px;line-height:1.6}button{display:block;width:100%;padding:13px;margin-top:12px;border:0;border-radius:8px;background:#198754;color:#fff;font-size:16px;cursor:pointer}</style>" +
    "</head><body><div class='box'><div class='icon'>" + icon + "</div><h1>" + title + "</h1><p>" + safeMessage + "</p>" +
    (success ? "<button onclick=\"window.location.href='https://computerprachi.online/find-tutor.html'\">🔙 Back to Teacher Profile</button>" : "") +
    "</div></body></html>";
  return HtmlService.createHtmlOutput(html);
}

function createRazorpayPaymentLink(referenceId,data,description,referencePrefix) {
  const keyId = PropertiesService.getScriptProperties().getProperty("RAZORPAY_KEY_ID");
  const keySecret = PropertiesService.getScriptProperties().getProperty("RAZORPAY_KEY_SECRET");
  if (!keyId) throw new Error("RAZORPAY_KEY_ID Script Property नहीं मिली।");
  if (!keySecret) throw new Error("RAZORPAY_KEY_SECRET Script Property नहीं मिली।");

  const payload = {
    amount:1000,
    currency:"INR",
    accept_partial:false,
    reference_id:referenceId,
    description:description,
    customer:{
      name:data.name || "Student",
      contact:data.mobile || "",
      email:data.email || ""
    },
    notify:{sms:false,email:false},
    reminder_enable:false,
    notes:{
      unlock_or_registration_id:referenceId,
      website:"Computer Prachi"
    },
    callback_url:CALLBACK_URL,
    callback_method:"get"
  };

  const auth = Utilities.base64Encode(keyId + ":" + keySecret);
  const response = UrlFetchApp.fetch(RAZORPAY_API,{
    method:"post",
    contentType:"application/json",
    headers:{Authorization:"Basic " + auth},
    payload:JSON.stringify(payload),
    muteHttpExceptions:true
  });

  const statusCode=response.getResponseCode();
  const text=response.getContentText();
  if(statusCode<200 || statusCode>=300) {
    throw new Error("Razorpay Payment Link नहीं बन पाया: " + text);
  }

  const result=JSON.parse(text);
  if(!result.id || !result.short_url) {
    throw new Error("Razorpay ने valid Payment Link नहीं दिया।");
  }
  return result;
}

function fetchPaymentLink(paymentLinkId) {
  const keyId=PropertiesService.getScriptProperties().getProperty("RAZORPAY_KEY_ID");
  const keySecret=PropertiesService.getScriptProperties().getProperty("RAZORPAY_KEY_SECRET");
  const auth=Utilities.base64Encode(keyId+":"+keySecret);
  const url=RAZORPAY_API+"/"+encodeURIComponent(paymentLinkId);
  const response=UrlFetchApp.fetch(url,{
    method:"get",
    headers:{Authorization:"Basic "+auth},
    muteHttpExceptions:true
  });
  const code=response.getResponseCode();
  if(code<200 || code>=300) throw new Error("Razorpay Payment Link status नहीं मिल पाया.");
  return JSON.parse(response.getContentText());
}

function saveStudentEnquiry(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName("Student Enquiries");
  if (!sh) sh = ss.insertSheet("Student Enquiries");

  const headers = [
    "Enquiry ID","Date/Time","Student Name","Mobile","WhatsApp","Email",
    "Class","Course/Subject","Board","City/District","Area/Locality",
    "Preferred Tutor","Gender Preference","Teaching Mode","Preferred Time",
    "Budget","Enquiry Message","Contact Status","Tutor Contacted","Enquiry Status"
  ];

  if (sh.getLastRow() === 0 || sh.getLastColumn() === 0) {
    sh.getRange(1,1,1,headers.length).setValues([headers]);
  } else {
    const existing = sh.getRange(1,1,1,sh.getLastColumn()).getValues()[0];
    headers.forEach(function(h) {
      if (existing.indexOf(h) === -1) {
        sh.getRange(1,sh.getLastColumn()+1).setValue(h);
        existing.push(h);
      }
    });
  }

  const enquiryId = "CP-E-" + Utilities.formatDate(
    new Date(), Session.getScriptTimeZone(), "yyyyMMdd-HHmmss"
  );

  const row = {
    "Enquiry ID": enquiryId,
    "Date/Time": new Date(),
    "Student Name": data.studentName || data.name || "",
    "Mobile": data.mobile || "",
    "WhatsApp": data.whatsapp || "",
    "Email": data.email || "",
    "Class": data.className || data.class || "",
    "Course/Subject": data.subject || data.courseSubject || "",
    "Board": data.board || "",
    "City/District": data.city || "",
    "Area/Locality": data.area || "",
    "Preferred Tutor": data.preferredTutor || data.tutorName || "",
    "Gender Preference": data.genderPreference || "",
    "Teaching Mode": data.teachingMode || data.mode || "",
    "Preferred Time": data.preferredTime || data.time || "",
    "Budget": data.budget || "",
    "Enquiry Message": data.message || data.enquiryMessage || "",
    "Contact Status": "New",
    "Tutor Contacted": "No",
    "Enquiry Status": "New"
  };

  const lastColumn = sh.getLastColumn();
  const currentHeaders = sh.getRange(1,1,1,lastColumn).getValues()[0];
  const values = currentHeaders.map(function(h) {
    return Object.prototype.hasOwnProperty.call(row,h) ? row[h] : "";
  });
  sh.appendRow(values);

  return jsonResponse({success:true,enquiryId:enquiryId,message:"Student enquiry submitted successfully."});
}

function findRowByHeader(sheet,header,value) {
  const headers=sheet.getRange(1,1,1,sheet.getLastColumn()).getValues()[0];
  const col=headers.indexOf(header)+1;
  if(!col) return 0;
  const last=sheet.getLastRow();
  if(last<2) return 0;
  const vals=sheet.getRange(2,col,last-1,1).getValues();
  for(let i=0;i<vals.length;i++) {
    if(String(vals[i][0])===String(value)) return i+2;
  }
  return 0;
}

function getByHeader(headers,row,header) {
  const i=headers.indexOf(header);
  return i >= 0 ? row[i] : "";
}

function getCellByHeader(sheet,row,header) {
  const headers=sheet.getRange(1,1,1,sheet.getLastColumn()).getValues()[0];
  const col=headers.indexOf(header)+1;
  return col ? sheet.getRange(row,col).getValue() : "";
}

function setCellByHeader(sheet,row,header,value) {
  const headers=sheet.getRange(1,1,1,sheet.getLastColumn()).getValues()[0];
  let col=headers.indexOf(header)+1;
  if(!col) {
    col=sheet.getLastColumn()+1;
    sheet.getRange(1,col).setValue(header);
  }
  sheet.getRange(row,col).setValue(value);
}

function bytesToHex(bytes) {
  return bytes.map(function(byte){
    const value=byte<0?byte+256:byte;
    return ("0"+value.toString(16)).slice(-2);
  }).join("");
}

function constantTimeEquals(a,b) {
  if(!a || !b || a.length!==b.length) return false;
  let result=0;
  for(let i=0;i<a.length;i++) result |= a.charCodeAt(i)^b.charCodeAt(i);
  return result===0;
}

function jsonResponse(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;")
    .replace(/'/g,"&#039;");
}

function authorizeUrlFetch() {
  UrlFetchApp.fetch("https://api.razorpay.com");
}
