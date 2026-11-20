// Bal Mandal Mobile App & PWA Controller
(function() {
  let deferredPrompt = null;
  const isIos = () => {
    const ua = window.navigator.userAgent;
    const isIosDevice = /iphone|ipad|ipod/i.test(ua);
    const isWebKit = /WebKit/i.test(ua);
    const isSafari = isIosDevice && isWebKit && !/CriOS/i.test(ua) && !/FxiOS/i.test(ua);
    return isIosDevice;
  };

  const isStandalone = () => {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true ||
      document.referrer.includes('android-app://')
    );
  };

  // If already running as an installed standalone app, tag document element
  if (isStandalone()) {
    document.documentElement.classList.add('is-standalone-app');
    console.log('[PWA] Running in Standalone Mobile App mode');
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    // Prevent the mini-infobar from appearing on mobile
    e.preventDefault();
    deferredPrompt = e;
    console.log('[PWA] beforeinstallprompt event captured');

    // Only show banner if user hasn't dismissed it in this session and not standalone
    if (!isStandalone()) {
      const dismissed = sessionStorage.getItem('pwa_banner_dismissed');
      if (!dismissed) {
        showInstallBanner();
      }
      // Also reveal any persistent install buttons (e.g. in drawer or header)
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.classList.remove('d-none');
      });
    }
  });

  window.addEventListener('appinstalled', () => {
    console.log('[PWA] Bal Mandal App was successfully installed');
    deferredPrompt = null;
    hideInstallBanner();
    document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
      btn.classList.add('d-none');
    });
    sessionStorage.setItem('pwa_banner_dismissed', '1');
  });

  function showInstallBanner() {
    const banner = document.getElementById('pwaInstallBanner');
    if (banner && !isStandalone()) {
      banner.classList.remove('d-none');
    }
  }

  function hideInstallBanner() {
    const banner = document.getElementById('pwaInstallBanner');
    if (banner) {
      banner.classList.add('d-none');
    }
  }

  window.dismissPwaBanner = function() {
    hideInstallBanner();
    sessionStorage.setItem('pwa_banner_dismissed', '1');
  };

  window.triggerPwaInstall = async function() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choiceResult = await deferredPrompt.userChoice;
      console.log('[PWA] User response to install prompt:', choiceResult.outcome);
      deferredPrompt = null;
      hideInstallBanner();
    } else if (isIos()) {
      // Show iOS modal guide
      const modalEl = document.getElementById('iosInstallModal');
      if (modalEl && window.bootstrap && window.bootstrap.Modal) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
      } else {
        alert("To install Bal Mandal App on iPhone:\n1. Tap the Share button at bottom of Safari\n2. Select 'Add to Home Screen'");
      }
    } else {
      // Browser fallback
      alert("To install Bal Mandal App:\nOpen your browser menu (⋮) and tap 'Add to Home Screen' or 'Install app'.");
    }
  };

  // Check on DOM ready
  document.addEventListener('DOMContentLoaded', () => {
    if (isStandalone()) {
      hideInstallBanner();
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.classList.add('d-none');
      });
    } else if (isIos()) {
      // On iOS Safari, show the install option in menu
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.classList.remove('d-none');
      });
      // Optionally show banner once if not dismissed
      const dismissed = sessionStorage.getItem('pwa_banner_dismissed');
      if (!dismissed) {
        showInstallBanner();
      }
    }
  });
})();
