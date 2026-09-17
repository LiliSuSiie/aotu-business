import http from 'k6/http';
import { check, fail } from 'k6';

// Reconstructed from eeds/进件.json. All customer data is supplied at runtime;
// the recording's personal data, encrypted values, images, and tokens are not reused.
const cfg = {
  baseUrl: (__ENV.BASE_URL || '').replace(/\/$/, ''),
  authorization: __ENV.AUTHORIZATION || '',
  enterpriseCode: __ENV.ENTERPRISE_CODE || '',
  productCode: __ENV.PRODUCT_CODE || '',
  mode: __ENV.MODE || 'read',
};

const requiredForFull = [
  'NAME_CIPHER', 'ID_CARD_CIPHER',
  'PHONE_CIPHER', 'CONTACT_NAME_CIPHER', 'CONTACT_PHONE_CIPHER', 'VERIFY_CODE',
];

// k6 只能在初始化阶段读取本地二进制文件。仅 full 模式读取，read/prepare
// 不要求测试图片存在。图片由本机私有 fixtures 提供，绝不从录制报文复制。
let frontImage;
let backImage;
if (cfg.mode === 'full') {
  frontImage = open('./fixtures/id-front.jpg', 'b');
  backImage = open('./fixtures/id-back.jpg', 'b');
}

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: { http_req_failed: ['rate==0'] },
};

function parse(response, stage) {
  let payload;
  try {
    payload = response.json();
  } catch (_) {
    fail(`${stage}: response is not JSON (HTTP ${response.status})`);
  }
  check(response, {
    [`${stage}: HTTP 2xx`]: (r) => r.status >= 200 && r.status < 300,
    [`${stage}: business code is 0`]: () => payload.code === '0' || payload.code === 0,
  });
  if (response.status < 200 || response.status >= 300 || (payload.code !== '0' && payload.code !== 0)) {
    fail(`${stage}: HTTP=${response.status}, businessCode=${payload.code}, msg=${payload.msg || ''}`);
  }
  return payload;
}

function gatewayHeaders() {
  return {
    Authorization: cfg.authorization,
    Device: 'H5',
    EnterpriseCode: cfg.enterpriseCode,
    'Content-Type': 'application/json;charset=UTF-8',
    Accept: 'application/json',
  };
}

function uploadHeaders() {
  // 不设置 Content-Type：k6 会为 multipart/form-data 自动生成 boundary。
  return {
    Authorization: cfg.authorization,
    Device: 'H5',
    EnterpriseCode: cfg.enterpriseCode,
    Accept: 'application/json',
  };
}

function gateway(logicalPath, logicalMethod, body, stage) {
  const envelope = {
    requestUrl: logicalPath,
    requestMode: logicalMethod,
    header: { authorization: cfg.authorization },
    body,
  };
  const response = http.post(
    `${cfg.baseUrl}/backend/comm/gateway/forward`,
    JSON.stringify(envelope),
    { headers: gatewayHeaders(), tags: { stage, logical_path: logicalPath } },
  );
  return parse(response, stage);
}

function uploadImage(reqCode, image, filename, bizType, stage) {
  const response = http.post(
    `${cfg.baseUrl}/backend/comm/files/upload/v1`,
    {
      bizCode: reqCode,
      multipartFile: http.file(image, filename, 'image/jpeg'),
      bizType,
      enterpriseCode: cfg.enterpriseCode,
    },
    { headers: uploadHeaders(), tags: { stage, biz_type: bizType } },
  );
  return parse(response, stage);
}

function assertConfig() {
  if (!cfg.baseUrl) fail('BASE_URL is required. Use an isolated test environment.');
  if (cfg.mode === 'prepare' || cfg.mode === 'full') {
    if (!cfg.productCode) fail('PRODUCT_CODE is required for prepare/full mode.');
  }
  if (cfg.mode === 'full') {
    const missing = requiredForFull.filter((name) => !__ENV[name]);
    if (missing.length) fail(`MODE=full missing variables: ${missing.join(', ')}`);
  }
  if (!['read', 'prepare', 'full'].includes(cfg.mode)) fail('MODE must be read, prepare, or full.');
}

function loadDictionaries() {
  const response = http.get(
    `${cfg.baseUrl}/backend/comm/sys/dict/items?code=education,nation,sex,hyzk,ssq`,
    { headers: gatewayHeaders(), tags: { stage: 'dictionary' } },
  );
  const payload = parse(response, 'dictionary');
  const data = payload.data || {};
  check(payload, {
    'dictionary: required groups returned': () => ['education', 'nation', 'sex', 'hyzk', 'ssq']
      .every((key) => Object.prototype.hasOwnProperty.call(data, key)),
  });
  return payload;
}

function acquireRequestCode() {
  const payload = gateway('/comm/moblie/loan/code', 'GET', { prdCode: cfg.productCode }, 'loan-code');
  const reqCode = payload.data && payload.data.reqCode;
  if (!reqCode) fail('loan-code: data.reqCode is missing');
  return reqCode;
}

function fileAndOcr(reqCode, image, filename, bizType, stage) {
  uploadImage(reqCode, image, filename, bizType, `${stage}-upload`);
  const files = gateway('/comm/moblie/files/list/v2/', 'GET', { bizCode: reqCode, bizType }, `${stage}-file-list`);
  check(files, { [`${stage}-file-list: data is present`]: (p) => p.data !== undefined && p.data !== null });
  // 录制流显示 OCR 入参 code 为进件 reqCode；文件与进件通过 bizCode 关联。
  return gateway('/comm/moblie/loan/ocr', 'POST', { code: reqCode, bizType }, `${stage}-ocr`);
}

function authorize(reqCode) {
  const authorizations = [
    [13, 'DZRZFW_READ'], [2, 'GRZXKH_READ'], [1, 'GRXXCX_READ'], [7, 'GRSQ_READ'],
  ];
  authorizations.forEach(([authType, signSealNodeTypeEnum]) => {
    gateway('/comm/tpl/authSample', 'GET', {
      bizCode: reqCode,
      enterpriseCode: cfg.enterpriseCode,
      authType,
      name: __ENV.DISPLAY_NAME || 'ATRC_TEST_USER',
      idcardNo: __ENV.ID_CARD_CIPHER,
    }, `auth-sample-${authType}`);
    gateway('/comm/sign/seal/opration/save', 'POST', {
      bizCode: reqCode,
      name: __ENV.DISPLAY_NAME || 'ATRC_TEST_USER',
      operationType: 'END',
      signSealNodeTypeEnum,
    }, `sign-${authType}`);
  });
}

function verifyPhone(reqCode) {
  gateway('/comm/moblie/loan/customer/telephone', 'POST', {
    telephone: __ENV.PHONE_CIPHER,
    reqCode,
    name: __ENV.DISPLAY_NAME || 'ATRC_TEST_USER',
  }, 'send-sms');
  gateway('/comm/moblie/loan/customer/verifycode', 'POST', {
    telephone: __ENV.PHONE_CIPHER,
    verifyCode: __ENV.VERIFY_CODE,
  }, 'verify-sms');
}

function saveCustomer(reqCode, frontOcr) {
  const data = frontOcr.data || {};
  const idImg = __ENV.ID_IMG_BASE64 || data.idImg;
  if (!idImg) fail('customer-save: ID_IMG_BASE64 is required when front OCR does not return data.idImg');
  gateway('/comm/moblie/loan/customer/save', 'POST', {
    custName: __ENV.NAME_CIPHER,
    nation: __ENV.NATION || '1',
    custSex: __ENV.CUST_SEX || '2',
    idCardNo: __ENV.ID_CARD_CIPHER,
    validDate: __ENV.VALID_DATE || '长期',
    residentialRegion: __ENV.RESIDENTIAL_REGION || '110000,110100,110101',
    residentialExact: __ENV.RESIDENTIAL_EXACT || 'ATRC测试地址',
    currentLivingAddress: __ENV.CURRENT_LIVING_ADDRESS || 'ATRC测试地址',
    phoneNumber: __ENV.PHONE_CIPHER,
    education: __ENV.EDUCATION || '1',
    personYearIncome: __ENV.PERSON_YEAR_INCOME || '111',
    homeYearIncome: __ENV.HOME_YEAR_INCOME || '333',
    maritalStatus: __ENV.MARITAL_STATUS || '5',
    enterpriseCode: cfg.enterpriseCode,
    code: reqCode,
    idImg,
    applyAmount: __ENV.APPLY_AMOUNT || '200000',
    loanUse: __ENV.LOAN_USE || '2',
    loanUseDesc: __ENV.LOAN_USE_DESC || 'O8010',
    emergencyContactRelation: __ENV.CONTACT_RELATION || '6',
    emergencyContactName: __ENV.CONTACT_NAME_CIPHER,
    emergencyContactTelphone: __ENV.CONTACT_PHONE_CIPHER,
  }, 'customer-save');
}

function livenessAndSubmit(reqCode) {
  gateway('/comm/moblie/live/check/url', 'GET', { bizCode: reqCode }, 'liveness-url');
  const liveness = gateway('/comm/moblie/live/check/result', 'POST', { bizCode: reqCode }, 'liveness-result');
  check(liveness, { 'liveness-result: result is present': (p) => p.data && p.data.result !== undefined });
  const submit = gateway('/comm/moblie/micro/access', 'POST', { reqCode }, 'micro-access');
  check(submit, { 'micro-access: accepted': (p) => !p.data || p.data.success === undefined || p.data.success === true });
}

export default function () {
  assertConfig();
  loadDictionaries();
  if (cfg.mode === 'read') return;

  const reqCode = acquireRequestCode();
  if (cfg.mode === 'prepare') return;

  const frontOcr = fileAndOcr(reqCode, frontImage, 'id-front.jpg', 'LOAN_PERSON_IDENTITY_FRONT', 'front');
  fileAndOcr(reqCode, backImage, 'id-back.jpg', 'LOAN_PERSON_IDENTITY_BACK', 'back');
  authorize(reqCode);
  verifyPhone(reqCode);
  saveCustomer(reqCode, frontOcr);
  livenessAndSubmit(reqCode);
  console.log(`ATRC_INTAKE_RESULT ${JSON.stringify({ reqCode, mode: cfg.mode, completedAt: new Date().toISOString() })}`);
}
