/**
 * Datalize – gửi mail certificate cho học viên, chạy ngay trong Google Sheet.
 *
 * Cài đặt (admin làm 1 lần, đăng nhập bằng tài khoản Google của Datalize):
 *   Sheet → Extensions → Apps Script → dán toàn bộ file này → Save → tải lại Sheet.
 *   Menu "Datalize" xuất hiện trên thanh menu của Sheet.
 *
 * Mail được gửi từ tài khoản Google của NGƯỜI BẤM menu, nên hãy bấm bằng tài khoản Datalize.
 *
 * Chỉ gửi cho dòng thoả MỌI điều kiện:
 *   status = Issued, có email (không phải @example.com), có cert_link, cột emailed_at còn trống.
 * Gửi xong, script ghi thời gian vào emailed_at, nên bấm lại cũng không gửi trùng.
 * Muốn gửi lại cho một người (vd. sau khi sửa tên): xoá ô emailed_at của dòng đó rồi bấm gửi.
 * Cột review/note KHÔNG được đưa vào mail.
 *
 * Gửi tự động: menu Datalize → "Bật gửi tự động (mỗi giờ)". Từ đó, sau khi issue.bat đổi dòng sang Issued
 * và trang cert đã online, mail tự đi trong vòng 1 giờ, không cần bấm gì. Tắt bằng "Tắt gửi tự động".
 */

const CFG = {
  tab: 'Students',
  senderName: 'Datalize',
  replyTo: '',            // vd. 'contact@datalize.cloud'; để trống thì học viên trả lời về tài khoản gửi
  logoUrl: 'https://certificate.datalize.cloud/assets/logo.png',
  website: 'https://datalize.cloud',
  courses: { PBI: 'Power BI for Business Users' },  // giữ khớp config.json → courses
  skipDomains: ['example.com'],
};

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Datalize')
    .addItem('Gửi thử 1 mail cho tôi', 'sendTestToMe')
    .addItem('Gửi mail certificate', 'sendCertMails')
    .addSeparator()
    .addItem('Bật gửi tự động (mỗi giờ)', 'enableAutoSend')
    .addItem('Tắt gửi tự động', 'disableAutoSend')
    .addToUi();
}

// ---------- gửi tự động ----------
// Khi bật, Google chạy autoSendCertMails() mỗi giờ bằng tài khoản của người đã bật.
// Chỉ gửi khi trang cert đã online (link trả về 200), để học viên không nhận link 404 khi hosting chưa deploy xong.

function enableAutoSend() {
  disableAutoSend_();
  ScriptApp.newTrigger('autoSendCertMails').timeBased().everyHours(1).create();
  SpreadsheetApp.getUi().alert('Đã bật gửi tự động. Mỗi giờ script sẽ gửi mail cho các dòng Issued chưa gửi, '
    + 'từ tài khoản ' + Session.getActiveUser().getEmail() + '.');
}

function disableAutoSend() {
  const n = disableAutoSend_();
  SpreadsheetApp.getUi().alert(n ? 'Đã tắt gửi tự động.' : 'Gửi tự động đang không bật.');
}

function disableAutoSend_() {
  let n = 0;
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'autoSendCertMails') { ScriptApp.deleteTrigger(t); n++; }
  });
  return n;
}

function autoSendCertMails() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;          // một lần chạy khác đang gửi
  try {
    const { sheet, col, rows } = pendingRows_();
    const live = rows.filter(r => isLive_(r.link));
    const quota = MailApp.getRemainingDailyQuota();
    const res = sendRows_(sheet, col, live.slice(0, quota));
    if (res.failed.length) console.error('Gửi lỗi:\n' + res.failed.join('\n'));
    console.log('Tự động: gửi ' + res.sent + ', chờ trang online ' + (rows.length - live.length)
      + ', để mai vì hết hạn mức ' + Math.max(0, live.length - quota));
  } finally {
    lock.releaseLock();
  }
}

function isLive_(url) {
  try {
    return UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true }).getResponseCode() === 200;
  } catch (e) {
    return false;
  }
}

/** Gửi mail của dòng đầu tiên đủ điều kiện tới chính người đang bấm, để xem trước. Không ghi emailed_at. */
function sendTestToMe() {
  const ui = SpreadsheetApp.getUi();
  const { rows } = pendingRows_();
  if (!rows.length) return ui.alert('Không có dòng nào cần gửi.');
  const me = Session.getActiveUser().getEmail();
  if (!me) return ui.alert('Không lấy được email của bạn. Hãy chạy bằng tài khoản Google có quyền với Sheet này.');
  const msg = buildMail_(rows[0]);
  GmailApp.sendEmail(me, '[THỬ] ' + msg.subject, msg.text, mailOptions_(msg.html));
  ui.alert('Đã gửi mail thử (nội dung của ' + rows[0].name + ') tới ' + me + '.');
}

/** Gửi cho mọi dòng đủ điều kiện, sau khi hỏi xác nhận. */
function sendCertMails() {
  const ui = SpreadsheetApp.getUi();
  const { sheet, col, rows } = pendingRows_();
  if (!rows.length) return ui.alert('Không có dòng nào cần gửi.');

  const quota = MailApp.getRemainingDailyQuota();
  if (rows.length > quota) {
    return ui.alert('Hôm nay chỉ còn gửi được ' + quota + ' mail, cần ' + rows.length + '. Hãy gửi lại vào ngày mai.');
  }
  const list = rows.map(r => '• ' + r.name + ' <' + r.email + '>').join('\n');
  const ok = ui.alert('Gửi mail certificate cho ' + rows.length + ' học viên?', list, ui.ButtonSet.YES_NO);
  if (ok !== ui.Button.YES) return;

  const { sent, failed } = sendRows_(sheet, col, rows);
  ui.alert('Đã gửi ' + sent + '/' + rows.length + ' mail.' + (failed.length ? '\n\nLỗi:\n' + failed.join('\n') : ''));
}

// ---------- helpers ----------

function sendRows_(sheet, col, rows) {
  let sent = 0;
  const failed = [];
  for (const r of rows) {
    try {
      const msg = buildMail_(r);
      GmailApp.sendEmail(r.email, msg.subject, msg.text, mailOptions_(msg.html));
      sheet.getRange(r.rowNum, col.emailed_at + 1)
        .setValue(Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm'));
      SpreadsheetApp.flush();               // ghi ngay, để lỗi giữa chừng không làm gửi trùng lần sau
      sent++;
    } catch (e) {
      failed.push(r.name + ': ' + e.message);
    }
  }
  return { sent, failed };
}

function pendingRows_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CFG.tab);
  if (!sheet) throw new Error('Không tìm thấy tab ' + CFG.tab);
  const values = sheet.getDataRange().getDisplayValues();
  const head = values[0].map(h => String(h).trim().toLowerCase());

  if (head.indexOf('emailed_at') < 0) {   // tự thêm cột nếu chưa có
    sheet.getRange(1, head.length + 1).setValue('emailed_at');
    head.push('emailed_at');
  }
  const col = {};
  ['name', 'email', 'course', 'type', 'status', 'cert_id', 'cert_link', 'emailed_at'].forEach(k => {
    col[k] = head.indexOf(k);
    if (col[k] < 0) throw new Error('Sheet thiếu cột ' + k);
  });

  const rows = [];
  values.slice(1).forEach((v, i) => {
    const get = k => String(v[col[k]] || '').trim();
    const email = get('email').toLowerCase();
    if (get('status').toLowerCase() !== 'issued') return;
    if (!get('name') || !email || !get('cert_link') || get('emailed_at')) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return;
    if (CFG.skipDomains.some(d => email.endsWith('@' + d))) return;
    rows.push({
      rowNum: i + 2,
      name: get('name').replace(/\s+/g, ' '),
      email: email,
      course: CFG.courses[get('course').toUpperCase()] || get('course'),
      type: get('type').toLowerCase() || 'completion',
      certId: get('cert_id'),
      link: get('cert_link'),
    });
  });
  return { sheet, col, rows };
}

function mailOptions_(html) {
  const o = { name: CFG.senderName, htmlBody: html };
  if (CFG.replyTo) o.replyTo = CFG.replyTo;
  return o;
}

function buildMail_(r) {
  const kind = r.type === 'participation' ? 'Certificate of Participation' : 'Certificate of Completion';
  const subject = 'Chứng nhận khoá ' + r.course + ' của bạn đã sẵn sàng';
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const text = [
    'Chào ' + r.name + ',',
    '',
    'Chúc mừng bạn đã hoàn thành khoá ' + r.course + ' cùng Datalize.',
    'Chứng nhận (' + kind + ') của bạn đã được cấp:',
    r.link,
    'Mã chứng nhận: ' + r.certId,
    '',
    'Trên trang chứng nhận, bạn có thể:',
    '- tải bản PDF hoặc PNG;',
    '- bấm "Add to LinkedIn profile" để thêm vào mục Licenses & certifications trên LinkedIn (thông tin được điền sẵn);',
    '- chia sẻ link. Ai có link đều xác thực được chứng nhận qua mã ở trên.',
    '',
    'Nếu họ tên in trên chứng nhận chưa đúng, bạn chỉ cần trả lời mail này, Datalize sẽ cấp lại với cùng mã.',
    '',
    'Trân trọng,',
    'Đội ngũ Datalize',
    CFG.website,
  ].join('\n');

  const html =
    '<div style="background:#f4f6f9;padding:24px 12px;font-family:Arial,Helvetica,sans-serif;color:#1f2937">' +
    '<div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb">' +
      '<div style="padding:20px 28px;border-bottom:3px solid #C9A227">' +
        '<img src="' + CFG.logoUrl + '" alt="Datalize" height="40" style="display:block;height:40px">' +
      '</div>' +
      '<div style="padding:28px;font-size:15px;line-height:1.6">' +
        '<p style="margin:0 0 14px">Chào <b>' + esc(r.name) + '</b>,</p>' +
        '<p style="margin:0 0 14px">Chúc mừng bạn đã hoàn thành khoá <b>' + esc(r.course) + '</b> cùng Datalize. ' +
          'Chứng nhận <i>' + kind + '</i> của bạn đã được cấp.</p>' +
        '<p style="margin:24px 0;text-align:center">' +
          '<a href="' + esc(r.link) + '" style="background:#0B1F3A;color:#ffffff;text-decoration:none;padding:12px 26px;border-radius:6px;font-weight:bold;display:inline-block">Xem chứng nhận</a>' +
        '</p>' +
        '<p style="margin:0 0 14px;font-size:13px;color:#6b7280;text-align:center">Mã chứng nhận: <b style="color:#1f2937">' + esc(r.certId) + '</b><br>' +
          '<a href="' + esc(r.link) + '" style="color:#0EA5A0">' + esc(r.link) + '</a></p>' +
        '<p style="margin:20px 0 6px">Trên trang chứng nhận, bạn có thể:</p>' +
        '<ul style="margin:0 0 14px;padding-left:20px">' +
          '<li>tải bản PDF hoặc PNG;</li>' +
          '<li>bấm <b>Add to LinkedIn profile</b> để thêm vào mục Licenses &amp; certifications trên LinkedIn (thông tin được điền sẵn);</li>' +
          '<li>chia sẻ link. Ai có link đều xác thực được chứng nhận qua mã ở trên.</li>' +
        '</ul>' +
        '<p style="margin:0 0 14px">Nếu họ tên in trên chứng nhận chưa đúng, bạn chỉ cần trả lời mail này, Datalize sẽ cấp lại với cùng mã.</p>' +
        '<p style="margin:20px 0 0">Trân trọng,<br>Đội ngũ Datalize</p>' +
      '</div>' +
      '<div style="padding:14px 28px;background:#0B1F3A;color:#cbd5e1;font-size:12px">' +
        '<a href="' + CFG.website + '" style="color:#FFB900;text-decoration:none">datalize.cloud</a> · Get insights easier' +
      '</div>' +
    '</div></div>';

  return { subject, text, html };
}
