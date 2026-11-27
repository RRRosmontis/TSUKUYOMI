/* TSUKUYOMI ANCHOR — 主播认证页逻辑 */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let ME = null;
  let CONFIG = null;
  let selectedRoom = null;

  function badge(status) {
    const map = {
      approved: ['ok', '已开通 LIVE'], pending: ['warn', '审核中 PENDING'],
      rejected: ['bad', '已拒绝 REJECTED'], revoked: ['bad', '已吊销 REVOKED'],
    };
    const [cls, txt] = map[status] || ['warn', status];
    return `<span class="badge ${cls}">${txt}</span>`;
  }

  async function boot() {
    $('gateLoginBtn').addEventListener('click', () => Live.requireLogin());
    $('logoutBtn').addEventListener('click', () => Live.logoutToSso());

    await Live.exchangeFromUrl();
    if (!Live.requireLogin()) return;   // 未登录已跳转
    const { data } = await Live.api('/me');
    if (!data.ok) { Live.logout(); Live.requireLogin(); return; }
    ME = data;
    $('gate').style.display = 'none';
    $('app').style.display = '';

    const cfg = await Live.api('/config');
    CONFIG = cfg.data || {};
    $('tutMainSrv').textContent = (CONFIG.sites && CONFIG.sites['1'] && CONFIG.sites['1'].push_server) || '—';
    $('tutSubSrv').textContent = (CONFIG.sites && CONFIG.sites['2'] && CONFIG.sites['2'].push_server) || '—';

    renderIdentity(data);
    renderAnchor(data);
    renderRecords(data);
  }

  function renderIdentity(d) {
    $('meNickname').textContent = d.user.nickname;
    $('meUid').textContent = d.user.uid;
    $('meEmail').textContent = d.user.email;
    const t = (d.stats && typeof d.stats === 'object') ? d.stats : {};
    const tier = (d.user && d.user.live && typeof d.user.live.tier !== 'undefined')
      ? d.user.live : null;
    const el = $('meTier');
    if (tier && tier.tier >= 1) { el.className = 'badge ok'; el.textContent = '已激活 TIER ' + tier.tier; }
    else { el.className = 'badge warn'; el.textContent = '未激活 TIER 0'; }
  }

  function renderRecords(d) {
    const s = d.stats || {};
    $('statTotal').textContent = Live.fmtDur(s.total_seconds || 0);
    $('statCount').textContent = s.stream_count || 0;
    $('statRoom').textContent = (d.anchor && d.anchor.room_no) ? '#' + d.anchor.room_no : '—';
    Live.api('/me/records').then(({ data }) => {
      if (!data.ok) return;
      $('statTotal').textContent = Live.fmtDur(data.total_seconds || 0);
      $('statCount').textContent = data.count || 0;
      const rows = (data.records || []).map((r) => {
        const site = r.site === 1 ? '主站' : '副站';
        const dur = r.ended_at ? Live.fmtDur(r.duration_s || 0) : '<span class="hl">直播中 ON AIR</span>';
        return `<tr><td>${esc(r.started_at)}</td><td>${esc(r.ended_at || '—')}</td>` +
          `<td>${site}</td><td>${esc(r.title) || '—'}</td><td>${dur}</td><td>${esc(r.end_reason || '—')}</td></tr>`;
      });
      $('recordsBody').innerHTML = rows.length ? rows.join('') : '<tr><td colspan="6" class="dim">暂无直播记录</td></tr>';
    });
  }

  /* ---------- 主播资格卡 ---------- */
  async function renderAnchor(d) {
    const box = $('anchorBox');
    const a = d.anchor;
    if (!a) { box.innerHTML = applyFormHTML(); wireApplyForm(); await paintRoomMap(); return; }

    if (a.status === 'pending') {
      box.innerHTML = `
        <div class="kv"><span class="k">状态</span><span class="v">${badge('pending')}</span></div>
        <div class="kv"><span class="k">申请房间号</span><span class="v">#${a.room_no}</span></div>
        <div class="kv"><span class="k">申请时间</span><span class="v">${esc(a.created_at)}</span></div>
        <p class="dim" style="font-size:13px;margin-top:12px">管理员审批通过后，推流码将在此处发放。</p>`;
      return;
    }
    if (a.status === 'rejected' || a.status === 'revoked') {
      const reason = a.reject_reason || a.admin_note || '';
      box.innerHTML = `
        <div class="kv"><span class="k">状态</span><span class="v">${badge(a.status)}</span></div>
        <div class="kv"><span class="k">说明</span><span class="v">${esc(reason) || '—'}</span></div>
        <div class="spacer"></div>
        <div class="f-label">重新申请 · 选择新的房间号（1-100，确认后不可更改）</div>
        <div id="retryMap"></div>
        <div class="err" id="retryErr"></div>
        <button class="btn" id="retryBtn" disabled>重新申请</button>`;
      wireRetryForm();
      await paintRoomMapInto($('retryMap'), (room, btn) => {
        selectedRoom = room;
        btn.parentElement.querySelectorAll('.room-cell.sel').forEach((x) => x.classList.remove('sel'));
        btn.classList.add('sel');
        $('retryBtn').disabled = false;
      });
      $('retryBtn').addEventListener('click', async () => {
        if (!selectedRoom) return;
        const { data } = await Live.api('/apply/retry', { method: 'POST', body: { room: selectedRoom } });
        if (data.ok) { location.reload(); } else { $('retryErr').textContent = data.msg || '提交失败'; }
      });
      return;
    }

    /* approved */
    box.innerHTML = `
      <div class="kv"><span class="k">状态</span><span class="v">${badge('approved')}</span></div>
      <div class="kv"><span class="k">房间号（不可更改）</span><span class="v hl">#${a.room_no}</span></div>
      <div class="kv"><span class="k">主站</span><span class="v"><span class="badge ${a.main_enabled ? 'on' : 'bad'}">${a.main_enabled ? '可用 ENABLED' : '已停用'}</span></span></div>
      <div class="kv"><span class="k">副站</span><span class="v"><span class="badge ${a.sub_enabled ? 'on' : 'bad'}">${a.sub_enabled ? '可用 ENABLED' : '已停用'}</span></span></div>
      <div class="kv"><span class="k">最近直播</span><span class="v">${esc(a.last_live_at || '从未')}</span></div>
      <div class="spacer"></div>
      <div class="f-label">OBS 推流码 STREAM KEY（仅本人可见）</div>
      <div class="keybox">
        <input class="f-input" id="keyField" type="password" readonly value="${esc((a.room_no ? a.room_no + '?token=' : '') + (d.stream_key || ''))}">
        <button class="btn ghost" id="keyEye">显示</button>
        <button class="btn ghost" id="keyCopy">复制</button>
      </div>
      <div class="spacer"></div>
      <div class="f-label">直播间标题（观众可见，最长 100 字）</div>
      <div class="keybox">
        <input class="f-input" id="titleField" maxlength="100" value="${esc(a.title)}" placeholder="例如：深夜杂谈 · マイクラ">
        <button class="btn ghost" id="titleSave">保存</button>
      </div>
      <div class="ok-msg" id="titleMsg"></div>
      <p class="dim" style="font-size:12.5px;margin-top:10px">OBS 服务器地址见下方「开播教程」。推流码泄漏他人即可冒用你直播，请勿外传。可在管理员处重置。</p>`;
    const keyField = $('keyField');
    $('keyEye').addEventListener('click', (e) => {
      const hidden = keyField.type === 'password';
      keyField.type = hidden ? 'text' : 'password';
      e.target.textContent = hidden ? '隐藏' : '显示';
    });
    $('keyCopy').addEventListener('click', () => copyText(keyField.value, $('keyCopy')));
    document.querySelectorAll('[data-copy]').forEach((b) =>
      b.addEventListener('click', () => copyText(b.dataset.copy, b)));
    $('titleSave').addEventListener('click', async () => {
      const { data } = await Live.api('/me/title', { method: 'POST', body: { title: $('titleField').value } });
      $('titleMsg').textContent = data.ok ? '已保存 ✓' : (data.msg || '保存失败');
      $('titleMsg').className = data.ok ? 'ok-msg' : 'err';
    });
  }

  function copyText(text, btn) {
    const done = () => { const t = btn.textContent; btn.textContent = '已复制 ✓'; setTimeout(() => { btn.textContent = t; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(done);
    else {
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta); done();
    }
  }

  /* ---------- 房号地图 + 申请 ---------- */
  function applyFormHTML() {
    return `
      <p class="dim" style="font-size:13.5px;margin-bottom:12px">首次开播需要申请房间号：选择 1-100 中未被占用的号码，提交后由管理员审批；通过后发放推流码。<b>房间号申请通过后不可更改，主副站通用。</b></p>
      <div class="room-map-legend">
        <span class="l-free"><i></i>可选</span><span class="l-taken"><i></i>已占用</span>
        <span class="l-pending"><i></i>审批中</span><span class="l-live"><i></i>直播中</span>
      </div>
      <div id="applyMap"></div>
      <div class="err" id="applyErr"></div>
      <button class="btn" id="applyBtn" disabled>申请房间号</button>`;
  }

  async function paintRoomMap() { await paintRoomMapInto($('applyMap'), pickForApply); wireApplyPick(); }

  function pickForApply(room, btn) {
    if (btn.classList.contains('taken') || btn.classList.contains('pending') || btn.classList.contains('live')) return;
    selectedRoom = room;
    btn.parentElement.querySelectorAll('.room-cell.sel').forEach((x) => x.classList.remove('sel'));
    btn.classList.add('sel');
    const b = $('applyBtn'); if (b) b.disabled = false;
  }

  function wireApplyPick() { const b = $('applyBtn'); if (b && !b.dataset.wired) { b.dataset.wired = 1; b.addEventListener('click', submitApply); } }
  function wireApplyForm() { wireApplyPick(); }

  async function paintRoomMapInto(container, onPick) {
    if (!container) return;
    const { data } = await Live.api('/rooms/map');
    if (!data.ok) { container.innerHTML = '<div class="err">房间地图加载失败</div>'; return; }
    const rooms = data.rooms;
    let html = '<div class="room-map">';
    for (let i = 1; i <= 100; i++) {
      const st = rooms[String(i)] || 'free';
      html += `<div class="room-cell ${st}" data-room="${i}">${i}</div>`;
    }
    html += '</div>';
    container.innerHTML = html;
    container.querySelectorAll('.room-cell').forEach((cell) =>
      cell.addEventListener('click', () => onPick(Number(cell.dataset.room), cell)));
  }

  async function submitApply() {
    if (!selectedRoom) return;
    const { data } = await Live.api('/apply', { method: 'POST', body: { room: selectedRoom } });
    if (data.ok) { location.reload(); }
    else { const e = $('applyErr'); if (e) e.textContent = data.msg || '提交失败'; }
  }

  function wireRetryForm() { selectedRoom = null; }


  boot();
})();
