/* TSUKUYOMI live — 公共脚本：会话换票 / API 封装 / 登录门 */
(function () {
  const LIVE_API = 'https://api.rrrosmontis.icu/v1/live/api';
  const SSO_LOGIN = 'https://sso.rrrosmontis.icu/';
  const TOKEN_KEY = 'live_token';
  const USER_KEY = 'live_user';

  const Live = {
    API: LIVE_API,
    SSO_LOGIN,

    get token() { return localStorage.getItem(TOKEN_KEY) || ''; },
    set token(v) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); },

    get user() {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch (e) { return null; }
    },
    set user(v) { v ? localStorage.setItem(USER_KEY, JSON.stringify(v)) : localStorage.removeItem(USER_KEY); },

    param(name) { return new URLSearchParams(location.search).get(name) || ''; },

    async api(path, { method = 'GET', body } = {}) {
      const headers = {};
      if (this.token) headers['Authorization'] = 'Bearer ' + this.token;
      if (body) headers['Content-Type'] = 'application/json';
      let r;
      try {
        r = await fetch(this.API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
      } catch (e) {
        return { status: 0, data: { ok: false, code: 0, msg: '网络错误' } };
      }
      let data = {};
      try { data = await r.json(); } catch (e) {}
      return { status: r.status, data };
    },

    /* ?sso_token=xxx → 换 live 会话；无论成败都清掉该参数防止死循环 */
    async exchangeFromUrl() {
      const ssoTok = this.param('sso_token');
      if (!ssoTok) return false;
      let ok = false;
      try {
        const r = await fetch(this.API + '/auth/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sso_token: ssoTok }),
        });
        const data = await r.json();
        if (r.status === 200 && data.ok) {
          this.token = data.token;
          this.user = data.user;
          ok = true;
        }
      } catch (e) {}
      const u = new URL(location.href);
      u.searchParams.delete('sso_token');
      history.replaceState(null, '', u.toString());
      return ok;
    },

    /* 已登录 → true；未登录 → 跳 SSO 登录并带上当前地址（保留原有参数） */
    requireLogin() {
      if (this.token && this.user) return true;
      /* 死循环保险丝：30 秒内第 3 次跳转就停下 */
      const KEY = 'live_sso_redirects';
      const now = Date.now();
      let arr = [];
      try { arr = JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) {}
      arr = arr.filter((t) => now - t < 30000);
      if (arr.length >= 2) {
        document.body.innerHTML =
          '<div style="font-family:monospace;padding:60px 30px;text-align:center;color:#fff;background:#000">' +
          'SSO 登录跳转异常，已停止重定向。<br><br>' +
          '<a href="' + location.pathname + '" style="color:#8fb8d8">刷新页面重试</a></div>';
        return false;
      }
      arr.push(now);
      sessionStorage.setItem(KEY, JSON.stringify(arr));
      const u = new URL(location.href);
      u.searchParams.delete('sso_token');
      location.href = this.SSO_LOGIN + '?redirect=' + encodeURIComponent(u.toString());
      return false;
    },

    logout() { this.token = ''; this.user = ''; },

    /* 登出并回 SSO 清掉 SSO 会话（?logout=1），防止 reload 后被自动重新登录；
       随后停留在 SSO 登录页（带 redirect，用户重新登录后可回到本页） */
    logoutToSso() {
      this.logout();
      const back = location.origin + location.pathname;
      location.href = this.SSO_LOGIN + '?logout=1&redirect=' + encodeURIComponent(back);
    },

    fmtDur(s) {
      s = Math.max(0, Math.floor(s || 0));
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
      return (h ? h + 'h ' : '') + (h || m ? m + 'm ' : '') + ss + 's';
    },
  };

  window.Live = Live;

  /* UTC 时钟（顶栏装饰，存在 #utc-clock 才启动） */
  function initClock() {
    const el = document.getElementById('utc-clock');
    if (!el) return;
    const p = (n) => String(n).padStart(2, '0');
    const tick = () => {
      const d = new Date();
      el.textContent = 'UTC ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ':' + p(d.getUTCSeconds());
    };
    tick(); setInterval(tick, 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initClock);
  else initClock();
})();
