/**
 * 주식 AI 사이트 키트 - 상담 신청 저장 + 알림 메일
 *
 * ★ 모든 사이트가 이 시트 하나로 접수됩니다. '사이트' 열(맨 끝)에 어느 사이트에서 왔는지 표시.
 * 이미 배포된 스크립트를 이 코드로 바꿀 때: 붙여넣기 → 저장 → 배포 > 배포 관리 > 연필 > 버전: 새 버전 > 배포
 * (새 배포를 만들면 주소가 바뀌니 반드시 '배포 관리'에서 새 버전으로)
 */

// ★ 사이트 이름 (알림 메일 제목에 표시)
const SITE_NAME = '상담DB';

// ★ 신청이 들어오면 알림을 받을 이메일 (여러 개면 쉼표로)
const NOTIFY_EMAIL = '여기에@이메일.com';

const SHEET_NAME = '상담신청';
const HEADERS = ['접수일시', '이름', '연락처', '투자경험', '문의내용',
                 '개인정보동의', '광고수신동의', '신청 경로', '관심 종목', '신청페이지', '유입경로', '상태', '메모', '사이트'];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const p = (e && e.parameter) || {};

    // 기본 검증
    const name = clean_(p.name, 30);
    const phone = clean_(p.phone, 13);
    if (!/^01[016789]-?\d{3,4}-?\d{4}$/.test(phone)) return json_({ ok: false, error: 'invalid' });
    if (p.agree_privacy !== 'Y') return json_({ ok: false, error: 'no_consent' });
    if (p.website) return json_({ ok: true }); // 스팸봇은 조용히 무시

    const sheet = getSheet_();

    // 같은 번호로 10분 안에 중복 신청이면 저장하지 않음
    const last = sheet.getLastRow();
    if (last > 1) {
      const start = Math.max(2, last - 50);
      const rows = sheet.getRange(start, 1, last - start + 1, 3).getValues();
      const now = Date.now();
      if (rows.some(r => r[2] === phone && now - new Date(r[0]).getTime() < 10 * 60 * 1000)) {
        return json_({ ok: true, dup: true });
      }
    }

    const row = [
      new Date(), name, phone,
      clean_(p.exp, 20), clean_(p.msg, 500),
      'Y', p.agree_marketing === 'Y' ? 'Y' : 'N',
      clean_(p.source, 30), clean_(p.topic, 60), clean_(p.page, 300), clean_(p.ref, 300),
      '신규', '', siteOf_(p)
    ];
    sheet.appendRow(row);

    // 알림 메일
    if (NOTIFY_EMAIL && NOTIFY_EMAIL.indexOf('@') > 0 && NOTIFY_EMAIL.indexOf('여기에') < 0) {
      MailApp.sendEmail({
        to: NOTIFY_EMAIL,
        subject: '[' + row[13] + '] ' + (row[7] || '상담') + ' 신청 - ' + (row[8] || phone),
        body: '사이트: ' + row[13] + '\n신청 경로: ' + (row[7] || '-') + '\n관심 종목: ' + (row[8] || '-') + '\n연락처: ' + phone + '\n이름: ' + (name || '-') +
              '\n투자경험: ' + (row[3] || '-') + '\n문의내용: ' + (row[4] || '-') +
              '\n광고수신동의: ' + row[6] +
              '\n\n시트 바로가기: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl()
      });
    }
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// 브라우저로 URL을 열었을 때 작동 확인용
function doGet() {
  return json_({ ok: true, message: '접수 서버 정상 작동 중' });
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold').setBackground('#0F1B2D').setFontColor('#FFFFFF');
    sheet.getRange('C:C').setNumberFormat('@'); // 연락처 앞자리 0 유지
  }
  // 예전 시트(13열)에 '사이트' 열 제목이 없으면 추가
  if (sheet.getRange(1, HEADERS.length).getValue() !== HEADERS[HEADERS.length - 1]) {
    sheet.getRange(1, HEADERS.length).setValue(HEADERS[HEADERS.length - 1])
         .setFontWeight('bold').setBackground('#0F1B2D').setFontColor('#FFFFFF');
  }
  return sheet;
}

// 어느 사이트에서 온 신청인지: site 값 → 없으면 신청페이지 주소의 도메인
function siteOf_(p) {
  const s = clean_(p.site, 60);
  if (s) return s;
  const m = String(p.page || '').match(/^https?:\/\/([^\/?#]+)/);
  return m ? m[1] : '-';
}

// 수식 주입 방지 + 길이 제한
function clean_(v, max) {
  let s = String(v == null ? '' : v).trim().slice(0, max);
  if (/^[=+\-@]/.test(s) && !/^01/.test(s)) s = "'" + s;
  return s;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// 처음 한 번 실행해서 권한 승인 + 시트 생성 (편집기에서 이 함수 선택 후 ▶ 실행)
function setup() {
  getSheet_();
  if (NOTIFY_EMAIL.indexOf('여기에') < 0) {
    MailApp.sendEmail(NOTIFY_EMAIL, '[' + SITE_NAME + '] 알림 테스트', '알림 메일이 정상적으로 설정되었습니다.');
  }
}
