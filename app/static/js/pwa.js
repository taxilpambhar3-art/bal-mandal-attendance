// Bal Mandal Mobile App & PWA Controller
(function() {
  let deferredPrompt = null;

  // --- Splash Screen & Navigation Loading UI ---
  window.dismissSplashScreen = function() {
    const splash = document.getElementById('appSplashScreen');
    if (splash && !splash.classList.contains('fade-out')) {
      splash.classList.add('fade-out');
      setTimeout(() => {
        splash.style.display = 'none';
      }, 350);
    }
  };

  window.showProgressBar = function() {
    const bar = document.getElementById('appTopProgressBar');
    if (bar) {
      bar.classList.add('loading');
      bar.style.width = '0%';
      bar.style.opacity = '1';
      setTimeout(() => { bar.style.width = '35%'; }, 50);
      setTimeout(() => { bar.style.width = '75%'; }, 250);
      setTimeout(() => { bar.style.width = '90%'; }, 600);
    }
  };

  window.hideProgressBar = function() {
    const bar = document.getElementById('appTopProgressBar');
    if (bar) {
      bar.style.width = '100%';
      setTimeout(() => {
        bar.style.opacity = '0';
        setTimeout(() => {
          bar.classList.remove('loading');
          bar.style.width = '0%';
        }, 250);
      }, 150);
    }
  };

  // Dismiss splash screen on window load with slight delay for silky smoothness
  window.addEventListener('load', () => {
    setTimeout(window.dismissSplashScreen, 180);
    window.hideProgressBar();
  });

  // Pageshow event (handles back/forward browser cache navigation)
  window.addEventListener('pageshow', () => {
    window.dismissSplashScreen();
    window.hideProgressBar();
  });

  // Safety fallback: if window load took more than 2.5 seconds
  setTimeout(window.dismissSplashScreen, 2500);

  // Link navigation progress bar trigger
  document.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (!link) return;
    const href = link.getAttribute('href');
    const target = link.getAttribute('target');
    if (!href || href.startsWith('#') || href.startsWith('javascript:') || target === '_blank') return;
    if (href.startsWith('/') || href.startsWith(window.location.origin)) {
      window.showProgressBar();
    }
  });

  // Form submission progress bar trigger
  document.addEventListener('submit', () => {
    window.showProgressBar();
  });

  // --- PWA Installation & Standalone detection ---
  const isIos = () => {
    const ua = window.navigator.userAgent;
    const isIosDevice = /iphone|ipad|ipod/i.test(ua);
    return isIosDevice;
  };

  const isStandalone = () => {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true ||
      document.referrer.includes('android-app://')
    );
  };

  if (isStandalone()) {
    document.documentElement.classList.add('is-standalone-app');
    console.log('[PWA] Running in Standalone Mobile App mode');
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    console.log('[PWA] beforeinstallprompt event captured');

    if (!isStandalone()) {
      const dismissed = sessionStorage.getItem('pwa_banner_dismissed');
      if (!dismissed) {
        showInstallBanner();
      }
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
      const modalEl = document.getElementById('iosInstallModal');
      if (modalEl && window.bootstrap && window.bootstrap.Modal) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
      } else {
        alert("To install Bal Mandal App on iPhone:\n1. Tap the Share button at bottom of Safari\n2. Select 'Add to Home Screen'");
      }
    } else {
      alert("To install Bal Mandal App:\nOpen your browser menu (⋮) and tap 'Add to Home Screen' or 'Install app'.");
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    if (isStandalone()) {
      hideInstallBanner();
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.classList.add('d-none');
      });
    } else if (isIos()) {
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.classList.remove('d-none');
      });
      const dismissed = sessionStorage.getItem('pwa_banner_dismissed');
      if (!dismissed) {
        showInstallBanner();
      }
    }
  });
})();
