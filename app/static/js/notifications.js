// Bal Mandal Notification & Event Alert Controller
(function() {
  let lastSeenNotifId = parseInt(localStorage.getItem('last_seen_notif_id') || '0', 10);
  let activeNotifications = [];

  // Pleasant Web Audio Chime Synthesizer
  function playNotificationChime() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      
      const now = ctx.currentTime;
      // Note 1: E5 (659.25Hz)
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(659.25, now);
      gain1.gain.setValueAtTime(0, now);
      gain1.gain.linearRampToValueAtTime(0.18, now + 0.04);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.36);

      // Note 2: A5 (880Hz)
      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(880.0, now + 0.12);
      gain2.gain.setValueAtTime(0, now + 0.12);
      gain2.gain.linearRampToValueAtTime(0.22, now + 0.16);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.56);
    } catch(e) {
      // Audio autoplay policies or unsupported browser
    }
  }

  // Request Device Notification Permission
  window.requestNotificationPermission = async function() {
    if (!('Notification' in window)) {
      alert('This browser does not support desktop notifications.');
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      updatePermissionBanner();
      if (permission === 'granted') {
        showToastNotification({
          title: '🔔 Notifications Enabled',
          message: 'You will now receive alerts whenever a new event or message is added!'
        });
      }
    } catch(e) {
      console.warn('Permission request error:', e);
    }
  };

  function updatePermissionBanner() {
    const banner = document.getElementById('notifPermissionBanner');
    if (!banner) return;
    if (!('Notification' in window) || Notification.permission === 'granted') {
      banner.classList.add('d-none');
    } else {
      banner.classList.remove('d-none');
    }
  }

  // Display native device notification
  function showDeviceNotification(notif) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const title = notif.title || '📅 Bal Mandal Announcement';
    const body = notif.message ? notif.message.replace(/\n\n/g, ' • ') : 'New event scheduled. Tap to view.';

    if ('serviceWorker' in navigator && navigator.serviceWorker.ready) {
      navigator.serviceWorker.ready.then(reg => {
        reg.showNotification(title, {
          body: body,
          icon: '/static/img/icon-192.png',
          badge: '/static/img/icon-192.png',
          vibrate: [200, 100, 200],
          data: { url: notif.link_url || '/' }
        });
      }).catch(() => {
        try { new Notification(title, { body: body, icon: '/static/img/icon-192.png' }); } catch(e){}
      });
    } else {
      try { new Notification(title, { body: body, icon: '/static/img/icon-192.png' }); } catch(e){}
    }
  }

  // Display on-screen animated toast notification
  function showToastNotification(notif) {
    const toastContainer = document.getElementById('notificationToastContainer');
    if (!toastContainer) return;

    const toastId = 'toast_' + Date.now();
    const html = `
      <div id="${toastId}" class="custom-notif-toast" role="alert">
        <div class="d-flex align-items-start gap-2">
          <div class="notif-toast-icon">
            <i class="bi bi-bell-fill"></i>
          </div>
          <div class="flex-grow-1 text-truncate">
            <div class="notif-toast-title text-truncate">${escapeHtml(notif.title)}</div>
            <div class="notif-toast-body text-truncate">${escapeHtml(notif.message || '')}</div>
          </div>
          <button type="button" class="btn-close btn-close-white btn-sm ms-2" onclick="dismissToast('${toastId}')"></button>
        </div>
      </div>
    `;
    toastContainer.insertAdjacentHTML('beforeend', html);
    const toastEl = document.getElementById(toastId);
    setTimeout(() => {
      if (toastEl) toastEl.classList.add('show');
    }, 50);

    setTimeout(() => {
      dismissToast(toastId);
    }, 6000);
  }

  window.dismissToast = function(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('show');
    setTimeout(() => { el.remove(); }, 300);
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Fetch Notifications from Server
  async function fetchNotifications(isInitial = false) {
    try {
      const res = await fetch('/api/notifications', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      activeNotifications = data.notifications || [];
      const unreadCount = data.unread_count || 0;

      updateBadges(unreadCount);

      if (activeNotifications.length > 0) {
        const topNotif = activeNotifications[0];
        if (!isInitial && topNotif.id > lastSeenNotifId && !topNotif.is_read) {
          // New notification arrived!
          lastSeenNotifId = topNotif.id;
          localStorage.setItem('last_seen_notif_id', topNotif.id);
          playNotificationChime();
          showToastNotification(topNotif);
          showDeviceNotification(topNotif);
        } else if (isInitial) {
          lastSeenNotifId = Math.max(lastSeenNotifId, topNotif.id);
          localStorage.setItem('last_seen_notif_id', lastSeenNotifId);
        }
      }

      // If drawer is open, render updated list
      const drawer = document.getElementById('notificationsOffcanvas');
      if (drawer && drawer.classList.contains('show')) {
        renderNotificationsList();
      }
    } catch(e) {
      console.warn('Notifications fetch error:', e);
    }
  }

  function updateBadges(count) {
    const navBadge = document.getElementById('navNotificationBadge');
    const drawerBadge = document.getElementById('drawerNotificationBadge');
    const bellBtn = document.querySelector('.nav-notification-btn');

    if (count > 0) {
      const displayCount = count > 99 ? '99+' : count;
      if (navBadge) {
        navBadge.textContent = displayCount;
        navBadge.classList.remove('d-none');
      }
      if (drawerBadge) {
        drawerBadge.textContent = displayCount;
        drawerBadge.classList.remove('d-none');
      }
      if (bellBtn) {
        bellBtn.classList.add('nav-bell-pulse');
      }
    } else {
      if (navBadge) navBadge.classList.add('d-none');
      if (drawerBadge) drawerBadge.classList.add('d-none');
      if (bellBtn) bellBtn.classList.remove('nav-bell-pulse');
    }
  }

  // Render notifications inside the offcanvas drawer
  function renderNotificationsList() {
    const listEl = document.getElementById('notificationsList');
    if (!listEl) return;

    if (activeNotifications.length === 0) {
      listEl.innerHTML = `
        <div class="text-center py-5 text-muted">
          <i class="bi bi-bell-slash fs-1 text-secondary opacity-50 mb-2 d-block"></i>
          <div class="fw-bold">No Notifications</div>
          <small class="text-muted">Event alerts and messages will appear here.</small>
        </div>
      `;
      return;
    }

    let html = '';
    activeNotifications.forEach((n) => {
      const unreadBadge = !n.is_read
        ? '<span class="badge bg-danger rounded-pill" style="font-size: 10px;">New</span>'
        : '';
      const cardBg = !n.is_read ? 'bg-primary-subtle border-primary-subtle' : 'bg-white border-light-subtle';

      let eventMetaHtml = '';
      if (n.event) {
        eventMetaHtml = `
          <div class="notif-event-meta p-2 rounded-2 mt-2 bg-light border">
            <div class="small fw-bold text-dark mb-1">
              <i class="bi bi-calendar-event me-1 text-primary"></i>${escapeHtml(n.event.title)}
            </div>
            <div class="small text-muted d-flex flex-wrap gap-2">
              <span><i class="bi bi-clock me-1"></i>${escapeHtml(n.event.event_date)} ${escapeHtml(n.event.event_time || '')}</span>
              ${n.event.location ? `<span><i class="bi bi-geo-alt me-1"></i>${escapeHtml(n.event.location)}</span>` : ''}
            </div>
          </div>
        `;
      }

      html += `
        <div class="card mb-2 shadow-xs border ${cardBg} rounded-3 notif-item" onclick="handleNotificationClick(${n.id}, '${escapeHtml(n.link_url || '/')}')">
          <div class="card-body p-3">
            <div class="d-flex align-items-start justify-content-between gap-2 mb-1">
              <h6 class="fw-bold mb-0 text-dark" style="font-size: 13.5px;">${escapeHtml(n.title)}</h6>
              <div class="d-flex align-items-center gap-1">
                ${unreadBadge}
                <span class="text-muted" style="font-size: 11px;">${escapeHtml(n.time_ago)}</span>
              </div>
            </div>
            ${n.message ? `<div class="notif-message-box p-2 my-2 rounded-2 text-dark bg-white border border-light" style="font-size: 12.5px; white-space: pre-wrap;"><i class="bi bi-chat-left-text me-1 text-danger"></i>${escapeHtml(n.message)}</div>` : ''}
            ${eventMetaHtml}
            <div class="d-flex align-items-center justify-content-between mt-2 pt-1 border-top" style="font-size: 11px;">
              <span class="text-muted"><i class="bi bi-person me-1"></i>${escapeHtml(n.creator_name)}</span>
              <a href="${escapeHtml(n.link_url || '/')}" class="text-primary fw-bold text-decoration-none">View Event <i class="bi bi-arrow-right"></i></a>
            </div>
          </div>
        </div>
      `;
    });

    listEl.innerHTML = html;
  }

  window.handleNotificationClick = async function(id, url) {
    try {
      await fetch('/api/notifications/mark-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ notification_id: id })
      });
      fetchNotifications();
    } catch(e) {}
    if (url && url !== '#') {
      window.location.href = url;
    }
  };

  window.markAllNotificationsRead = async function() {
    try {
      await fetch('/api/notifications/mark-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ mark_all: true })
      });
      fetchNotifications();
    } catch(e) {
      console.warn('Error marking all as read:', e);
    }
  };

  window.openNotificationDrawer = function() {
    renderNotificationsList();
    updatePermissionBanner();
    const offcanvasEl = document.getElementById('notificationsOffcanvas');
    if (offcanvasEl && window.bootstrap && window.bootstrap.Offcanvas) {
      const bsOffcanvas = bootstrap.Offcanvas.getOrCreateInstance(offcanvasEl);
      bsOffcanvas.show();
    }
  };

  // Start polling
  document.addEventListener('DOMContentLoaded', () => {
    fetchNotifications(true);
    updatePermissionBanner();
    setInterval(() => fetchNotifications(false), 25000);
  });
})();
