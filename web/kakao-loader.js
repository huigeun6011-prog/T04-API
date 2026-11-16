// config.local.js 의 키로 Kakao Maps SDK를 불러온다. 키가 없으면 SDK를 불러오지 않고,
// app.js 의 재시도 후 대체(노선도) 화면이 표시된다.
(function () {
  var key = window.APP_CONFIG && window.APP_CONFIG.kakaoAppKey;
  if (!key || key.indexOf('여기에') === 0) {
    console.warn('[kakao] web/config.local.js 에 kakaoAppKey 가 없습니다. config.example.js 를 참고하세요.');
    return;
  }
  var s = document.createElement('script');
  s.src = 'https://dapi.kakao.com/v2/maps/sdk.js?appkey=' + encodeURIComponent(key) + '&autoload=false&libraries=services';
  document.head.appendChild(s);
})();
