/* 全局轻量 UI:toast 通知 + 确认弹层。
 * 自带样式(用 tokens.css 的主题变量,跟随明暗主题),不依赖 Tailwind 生成,免 purge。
 * 暴露 window.rwToast(msg,type) 与 window.rwConfirm({title,message,okText,danger}) → Promise<bool>。
 */
(function () {
  if (window.rwToast) return;

  // 双提交 CSRF:把 csrf cookie 回显到 X-CSRF-Token 头(所有 mutating fetch 用)。
  // kubeconfig/bypass 模式后端整体跳过校验会忽略它;session 模式下必带否则 403。单一来源,模板别再各复制一份。
  window.rwCsrf = function () {
    var m = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  };

  var css = ''
    + '.rw-toasts{position:fixed;bottom:18px;right:18px;z-index:9999;display:flex;flex-direction:column;gap:8px;}'
    + '.rw-toast{min-width:220px;max-width:380px;padding:10px 14px;border-radius:8px;font-size:13px;font-weight:500;'
    + 'color:#fff;box-shadow:0 6px 18px rgba(0,0,0,.18);transition:opacity .2s,transform .2s;}'
    + '.rw-toast.ok{background:oklch(0.62 0.17 150);}'
    + '.rw-toast.err{background:var(--destructive,oklch(0.577 0.245 27.325));}'
    + '.rw-toast.info{background:oklch(0.45 0 0);}'
    + '.rw-mask{position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.45);display:flex;'
    + 'align-items:center;justify-content:center;animation:rw-fade .15s ease;}'
    + '@keyframes rw-fade{from{opacity:0}to{opacity:1}}'
    + '.rw-modal{background:var(--card,#fff);color:var(--card-foreground,#111);'
    + 'border:1px solid var(--border,#e5e7eb);border-radius:14px;padding:22px;width:min(92vw,400px);'
    + 'box-shadow:0 12px 40px rgba(0,0,0,.3);animation:rw-pop .15s ease;}'
    + '@keyframes rw-pop{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:none}}'
    + '.rw-modal-title{font-size:16px;font-weight:600;margin-bottom:8px;}'
    + '.rw-modal-body{font-size:14px;color:var(--muted-foreground,#666);margin-bottom:20px;line-height:1.5;}'
    + '.rw-modal-actions{display:flex;justify-content:flex-end;gap:8px;}'
    + '.rw-btn{height:36px;padding:0 16px;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;'
    + 'border:1px solid transparent;}'
    + '.rw-btn-ghost{background:transparent;border-color:var(--border,#e5e7eb);color:var(--foreground,#111);}'
    + '.rw-btn-primary{background:var(--primary,#2563eb);color:var(--primary-foreground,#fff);}'
    + '.rw-btn-danger{background:var(--destructive,#ef4444);color:var(--destructive-foreground,#fff);}'
    + '.rw-spin{display:inline-block;width:16px;height:16px;border:2px solid currentColor;'
    + 'border-right-color:transparent;border-radius:50%;animation:rw-rot .6s linear infinite;}'
    + '@keyframes rw-rot{to{transform:rotate(360deg)}}';
  var style = document.createElement('style');
  style.textContent = css;
  (document.head || document.documentElement).appendChild(style);

  window.rwToast = function (msg, type) {
    var root = document.getElementById('toast-root') || document.body;
    var box = root.querySelector('.rw-toasts');
    if (!box) { box = document.createElement('div'); box.className = 'rw-toasts'; root.appendChild(box); }
    var el = document.createElement('div');
    el.className = 'rw-toast ' + (type || 'info');
    el.textContent = msg;
    box.appendChild(el);
    var ttl = type === 'err' ? 4000 : 2600;
    setTimeout(function () {
      el.style.opacity = '0'; el.style.transform = 'translateY(8px)';
      setTimeout(function () { el.remove(); }, 220);
    }, ttl);
  };

  window.rwConfirm = function (opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var mask = document.createElement('div');
      mask.className = 'rw-mask';
      var modal = document.createElement('div');
      modal.className = 'rw-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      var title = document.createElement('div'); title.className = 'rw-modal-title'; title.textContent = opts.title || '确认';
      var body = document.createElement('div'); body.className = 'rw-modal-body'; body.textContent = opts.message || '';
      var actions = document.createElement('div'); actions.className = 'rw-modal-actions';
      var cancel = document.createElement('button'); cancel.className = 'rw-btn rw-btn-ghost'; cancel.textContent = opts.cancelText || '取消';
      var ok = document.createElement('button'); ok.className = 'rw-btn ' + (opts.danger ? 'rw-btn-danger' : 'rw-btn-primary'); ok.textContent = opts.okText || '确定';
      actions.appendChild(cancel); actions.appendChild(ok);
      modal.appendChild(title); modal.appendChild(body); modal.appendChild(actions);
      mask.appendChild(modal);

      function close(v) { mask.remove(); document.removeEventListener('keydown', onKey); resolve(v); }
      function onKey(e) { if (e.key === 'Escape') close(false); else if (e.key === 'Enter') close(true); }
      mask.addEventListener('click', function (e) { if (e.target === mask) close(false); });
      cancel.onclick = function () { close(false); };
      ok.onclick = function () { close(true); };
      document.addEventListener('keydown', onKey);
      document.body.appendChild(mask);
      ok.focus();
    });
  };
})();
