(function() {
  "use strict";

  /**
   * Apply .scrolled class to the body as the page is scrolled down
   */
  function toggleScrolled() {
    const selectBody = document.querySelector('body');
    const selectHeader = document.querySelector('#header');
    if (!selectHeader.classList.contains('scroll-up-sticky') && !selectHeader.classList.contains('sticky-top') && !selectHeader.classList.contains('fixed-top')) return;
    window.scrollY > 100 ? selectBody.classList.add('scrolled') : selectBody.classList.remove('scrolled');
  }

  document.addEventListener('scroll', toggleScrolled);
  window.addEventListener('load', toggleScrolled);

  /**
   * Mobile nav toggle
   */
  const mobileNavToggleBtn = document.querySelector('.mobile-nav-toggle');

  function mobileNavToogle() {
    document.querySelector('body').classList.toggle('mobile-nav-active');
    mobileNavToggleBtn.classList.toggle('bi-list');
    mobileNavToggleBtn.classList.toggle('bi-x');
  }
  if (mobileNavToggleBtn) {
    mobileNavToggleBtn.addEventListener('click', mobileNavToogle);
  }

  /**
   * Hide mobile nav on same-page/hash links
   */
  document.querySelectorAll('#navmenu a').forEach(navmenu => {
    navmenu.addEventListener('click', () => {
      if (document.querySelector('.mobile-nav-active')) {
        mobileNavToogle();
      }
    });

  });

  /**
   * Toggle mobile nav dropdowns
   */
  document.querySelectorAll('.navmenu .toggle-dropdown').forEach(navmenu => {
    navmenu.addEventListener('click', function(e) {
      e.preventDefault();
      this.parentNode.classList.toggle('active');
      this.parentNode.nextElementSibling.classList.toggle('dropdown-active');
      e.stopImmediatePropagation();
    });
  });

  /**
   * Sliding Notification System
   */
  window.SlideNotification = {
    show: function(message, type = 'info', duration = 4000) {
      // Force remove any existing notifications and alerts
      this.removeAllNotifications();
      
      // Create notification element
      const notification = document.createElement('div');
      notification.className = `slide-notification ${type}`;
      notification.style.zIndex = '2147483647'; // Force maximum z-index
      notification.style.position = 'fixed';
      
      // Get appropriate icon for notification type
      let icon = '';
      switch(type) {
        case 'success':
          icon = '<i class="bi bi-check-circle-fill notification-icon"></i>';
          break;
        case 'error':
        case 'danger':
          icon = '<i class="bi bi-exclamation-triangle-fill notification-icon"></i>';
          break;
        case 'warning':
          icon = '<i class="bi bi-exclamation-triangle-fill notification-icon"></i>';
          break;
        case 'info':
        default:
          icon = '<i class="bi bi-info-circle-fill notification-icon"></i>';
          break;
      }
      
      notification.innerHTML = `
        <div class="notification-content">
          ${icon}
          <span class="notification-text">${message}</span>
        </div>
        <button class="notification-close" onclick="SlideNotification.hide(this.parentElement)" aria-label="Close notification">
          <i class="bi bi-x"></i>
        </button>
      `;
      
      // Add to DOM at the very end of body to ensure highest stacking
      document.body.appendChild(notification);
      
      // Force maximum z-index on all child elements
      const allElements = notification.querySelectorAll('*');
      allElements.forEach(el => {
        el.style.zIndex = '2147483647';
      });
      
      // Force reflow to ensure transition works
      notification.offsetHeight;
      
      // Trigger slide in animation
      setTimeout(() => {
        notification.classList.add('show');
      }, 100);
      
      // Auto hide after duration
      if (duration > 0) {
        setTimeout(() => {
          this.hide(notification);
        }, duration);
      }
      
      return notification;
    },
    
    hide: function(notification) {
      if (notification && notification.parentElement) {
        notification.classList.remove('show');
        notification.classList.add('slide-out');
        
        // Remove from DOM after animation
        setTimeout(() => {
          if (notification.parentElement) {
            notification.parentElement.removeChild(notification);
          }
        }, 800);
      }
    },
    
    removeAllNotifications: function() {
      // Remove all existing slide notifications
      const existingNotifications = document.querySelectorAll('.slide-notification');
      existingNotifications.forEach(notification => {
        this.hide(notification);
      });
      
      // Force remove any Bootstrap alerts or other notification systems
      const alerts = document.querySelectorAll('.alert, .toast, [class*="notification"]:not(.slide-notification), [class*="flash"]');
      alerts.forEach(alert => {
        alert.style.display = 'none';
        alert.style.visibility = 'hidden';
        alert.style.opacity = '0';
        alert.style.height = '0';
        alert.style.zIndex = '-1';
        if (alert.parentElement) {
          alert.parentElement.removeChild(alert);
        }
      });
    }
  };

  /**
   * Process Flask flash messages and convert to sliding notifications
   */
  function processFlashMessages() {
    // First, aggressively remove any Bootstrap alerts
    const existingAlerts = document.querySelectorAll('.alert, .toast, [class*="alert"], [class*="flash"]:not(.flash-message-data)');
    existingAlerts.forEach(alert => {
      alert.style.display = 'none !important';
      alert.style.visibility = 'hidden !important';
      alert.style.opacity = '0 !important';
      alert.style.height = '0 !important';
      alert.style.zIndex = '-1 !important';
      alert.remove();
    });
    
    const flashMessages = document.querySelectorAll('.flash-message-data');
    flashMessages.forEach(messageElement => {
      const category = messageElement.dataset.category;
      const message = messageElement.dataset.message;
      
      // Show sliding notification at bottom of viewport with maximum z-index
      SlideNotification.show(message, category, 4000);
      
      // Remove the flash message element
      messageElement.remove();
    });
  }

  /**
   * Force cleanup of competing notification systems
   */
  function forceCleanupNotifications() {
    const competingElements = document.querySelectorAll('.alert, .toast, .bootstrap-alert, [class*="alert"], [role="alert"]');
    competingElements.forEach(el => {
      el.style.display = 'none !important';
      el.style.visibility = 'hidden !important';
      el.style.zIndex = '-999999 !important';
      el.remove();
    });
  }

  /**
   * Initialize sliding notifications on page load
   */
  window.addEventListener('load', function() {
    forceCleanupNotifications();
    setTimeout(processFlashMessages, 200);
  });

  // Also process messages on DOMContentLoaded for faster response
  document.addEventListener('DOMContentLoaded', function() {
    forceCleanupNotifications();
    setTimeout(processFlashMessages, 100);
  });

  // Periodic cleanup to ensure no competing notifications appear
  setInterval(forceCleanupNotifications, 2000);

  /**
   * Scroll top button
   */
  let scrollTop = document.querySelector('.scroll-top');

  function toggleScrollTop() {
    if (scrollTop) {
      window.scrollY > 100 ? scrollTop.classList.add('active') : scrollTop.classList.remove('active');
    }
  }
  scrollTop.addEventListener('click', (e) => {
    e.preventDefault();
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  });

  window.addEventListener('load', toggleScrollTop);
  document.addEventListener('scroll', toggleScrollTop);

  /**
   * Animation on scroll function and init
   */
  function aosInit() {
    AOS.init({
      duration: 600,
      easing: 'ease-in-out',
      once: true,
      mirror: false
    });
  }
  window.addEventListener('load', aosInit);

  /**
   * Initiate glightbox
   */
  const glightbox = GLightbox({
    selector: '.glightbox'
  });

  /**
   * Init swiper sliders
   */
  function initSwiper() {
    document.querySelectorAll(".init-swiper").forEach(function(swiperElement) {
      let config = JSON.parse(
        swiperElement.querySelector(".swiper-config").innerHTML.trim()
      );

      if (swiperElement.classList.contains("swiper-tab")) {
        initSwiperWithCustomPagination(swiperElement, config);
      } else {
        new Swiper(swiperElement, config);
      }
    });
  }

  window.addEventListener("load", initSwiper);

  /**
   * Initiate Pure Counter
   */
  new PureCounter();

  /**
   * Frequently Asked Questions Toggle
   */
  document.querySelectorAll('.faq-item h3, .faq-item .faq-toggle').forEach((faqItem) => {
    faqItem.addEventListener('click', () => {
      faqItem.parentNode.classList.toggle('faq-active');
    });
  });

  /**
   * Correct scrolling position upon page load for URLs containing hash links.
   */
  window.addEventListener('load', function(e) {
    if (window.location.hash) {
      if (document.querySelector(window.location.hash)) {
        setTimeout(() => {
          let section = document.querySelector(window.location.hash);
          let scrollMarginTop = getComputedStyle(section).scrollMarginTop;
          window.scrollTo({
            top: section.offsetTop - parseInt(scrollMarginTop),
            behavior: 'smooth'
          });
        }, 100);
      }
    }
  });

  /**
   * Navmenu Scrollspy
   */
  let navmenulinks = document.querySelectorAll('.navmenu a');

  function navmenuScrollspy() {
    navmenulinks.forEach(navmenulink => {
      if (!navmenulink.hash) return;
      let section = document.querySelector(navmenulink.hash);
      if (!section) return;
      let position = window.scrollY + 200;
      if (position >= section.offsetTop && position <= (section.offsetTop + section.offsetHeight)) {
        document.querySelectorAll('.navmenu a.active').forEach(link => link.classList.remove('active'));
        navmenulink.classList.add('active');
      } else {
        navmenulink.classList.remove('active');
      }
    })
  }
  window.addEventListener('load', navmenuScrollspy);
  document.addEventListener('scroll', navmenuScrollspy);

})();