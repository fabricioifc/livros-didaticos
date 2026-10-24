export const $ = (selector, scope = document) => scope.querySelector(selector);
export const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

export const elements = {
  authScreen: $("#auth-screen"),
  application: $("#application"),
  authForm: $("#auth-form"),
  authTitle: $("#auth-title"),
  authIntro: $("#auth-intro"),
  authSubmit: $("#auth-submit"),
  password: $("#password"),
  studentDialog: $("#student-dialog"),
  studentForm: $("#student-form"),
  detailDialog: $("#student-detail-dialog"),
  signatureDialog: $("#signature-dialog"),
  canvas: $("#signature-canvas"),
  toastRegion: $("#toast-region"),
};
