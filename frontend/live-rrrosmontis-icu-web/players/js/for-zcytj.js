/* ============================================================================
 * for-zcytj.js — 临时主站拉流线路改写（仅对 zcytj@aeolianchi.me 生效）
 *
 * 作用：SSO 登录用户 zcytj@aeolianchi.me 从「主站」观看直播时，
 *       把主站拉流地址的源站 https://api.rrrosmontis.icu 改写为
 *       https://live-api.zcytj.top（zcytj 中转）。
 *
 * 明确不改动：
 *   1. 副站拉流（https://subapi.rrrosmontis.icu/live/...）
 *   2. 两条弹幕 WebSocket（wss://api.rrrosmontis.icu/v1/live/danmaku、
 *      wss://subapi.rrrosmontis.icu/v1/live/danmaku）
 *   3. 其余任何 API 请求（live-common.js 的 L.API 保持不变）
 *
 * 控制台命令（页面加载后即可用）：
 *   ZCYTJ.status()    查看当前状态（开关 / 登录用户 / 是否生效 / 已改写次数）
 *   ZCYTJ.disable()   关闭本功能（写入 localStorage，刷新后依然关闭）
 *   ZCYTJ.enable()    重新开启本功能
 *   ZCYTJ.reset()     清除开关记录，恢复默认（开启）
 *   ZCYTJ.user()      查看当前识别到的 SSO 登录邮箱
 *
 * 关闭后若正在主站观看，player.html 会监听 zcytj-change 事件自动重连生效。
 * ==========================================================================*/
(function () {
    'use strict';

    var TARGET_EMAIL  = 'zcytj@aeolianchi.me';       // 仅该账号生效
    var MAIN_ORIGIN   = 'https://api.rrrosmontis.icu';
    var MAIN_ORIGIN_X = 'http://api.rrrosmontis.icu'; // 防御性：http 写法
    var ALT_ORIGIN    = 'https://live-api.zcytj.top';
    var STORE_KEY     = 'zcytj_rewrite_disabled';     // '1' = 已关闭

    var stats = { rewrites: 0, lastUrl: '' };

    function readDisabled() {
        try { return localStorage.getItem(STORE_KEY) === '1'; } catch (e) { return false; }
    }
    function writeDisabled(v) {
        try { v ? localStorage.setItem(STORE_KEY, '1') : localStorage.removeItem(STORE_KEY); } catch (e) {}
    }

    var disabled = readDisabled();

    function currentEmail() {
        try {
            var u = window.Live && window.Live.user;
            return (u && typeof u.email === 'string') ? u.email.trim().toLowerCase() : '';
        } catch (e) { return ''; }
    }
    function isTargetUser() { return currentEmail() === TARGET_EMAIL; }
    function isActive() { return !disabled && isTargetUser(); }

    /* 只认拉流地址：/live/<room>.flv|.m3u8（弹幕 /v1/... 与 API 一律不碰） */
    function isStreamPath(rest) {
        return rest.indexOf('/live/') === 0
            && (/\.flv($|\?)/.test(rest) || /\.m3u8($|\?)/.test(rest));
    }

    /* 改写整条拉流地址：仅主站 + 源站确为 api.rrrosmontis.icu + 确属拉流路径 */
    function rewriteStreamUrl(url, isMain) {
        if (!url || !isMain) return url;      // 副站一律不动
        if (!isActive()) return url;
        var rest = null;
        if (url.indexOf(MAIN_ORIGIN) === 0) rest = url.slice(MAIN_ORIGIN.length);
        else if (url.indexOf(MAIN_ORIGIN_X) === 0) rest = url.slice(MAIN_ORIGIN_X.length);
        if (rest === null || !isStreamPath(rest)) return url;
        stats.rewrites++;
        stats.lastUrl = ALT_ORIGIN + rest;
        return ALT_ORIGIN + rest;
    }

    /* 改写 base 写法（getStreamUrl 用得到） */
    function streamBase(isMain, base) {
        if (!isMain || !isActive()) return base;
        if (base === MAIN_ORIGIN + '/live/' || base === MAIN_ORIGIN_X + '/live/') {
            return ALT_ORIGIN + '/live/';
        }
        return base;
    }

    function notify() {
        try {
            window.dispatchEvent(new CustomEvent('zcytj-change', { detail: { active: isActive() } }));
        } catch (e) {}
    }

    function report(prefix) {
        var info = {
            '开关': disabled ? '关闭' : '开启',
            '目标账号': TARGET_EMAIL,
            '当前登录': currentEmail() || '(未登录)',
            '当前生效': isActive() ? '是' : '否',
            '已改写次数': stats.rewrites,
            '最后一次': stats.lastUrl || '-'
        };
        try { console.log('[ZCYTJ] ' + prefix, info); } catch (e) {}
        return info;
    }

    window.ZCYTJ = {
        target: TARGET_EMAIL,
        storeKey: STORE_KEY,
        get disabled() { return disabled; },
        get active() { return isActive(); },
        user: function () { return currentEmail() || '(未登录)'; },
        rewriteStreamUrl: rewriteStreamUrl,
        streamBase: streamBase,
        status: function () { return report('当前状态'); },
        disable: function () { disabled = true;  writeDisabled(true);  notify(); return report('已关闭'); },
        enable:  function () { disabled = false; writeDisabled(false); notify(); return report('已开启'); },
        reset:   function () { disabled = false; writeDisabled(false); notify(); return report('已重置（默认开启）'); }
    };

    try {
        console.log('[ZCYTJ] 主站拉流改写脚本已加载。控制台可用：ZCYTJ.status() / ZCYTJ.disable() / ZCYTJ.enable() / ZCYTJ.reset()');
    } catch (e) {}
})();
