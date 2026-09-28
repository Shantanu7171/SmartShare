// SmartShare Core Client Utilities (Clean Light Theme)

// Ensure light mode across the app
document.documentElement.classList.remove('dark');
try { localStorage.removeItem('theme'); } catch(e) {}

// JWT Session Management Helpers
window.setAuthSession = function(data) {
  if (data.access) localStorage.setItem('accessToken', data.access);
  if (data.refresh) localStorage.setItem('refreshToken', data.refresh);
  if (data.user) localStorage.setItem('currentUser', typeof data.user === 'object' ? JSON.stringify(data.user) : data.user);
};

window.clearAuthSession = function() {
  localStorage.removeItem('accessToken');
  localStorage.removeItem('refreshToken');
  localStorage.removeItem('currentUser');
};

// Sync JWT cookie and URL logout flags
(function syncAuthSession() {
  if (window.location.search.includes('logged_out=1')) {
    window.clearAuthSession();
  }
  const jwtCookie = document.cookie.split('; ').find(row => row.startsWith('jwt_access='));
  if (jwtCookie && !localStorage.getItem('accessToken')) {
    const tokenVal = jwtCookie.split('=')[1];
    if (tokenVal) localStorage.setItem('accessToken', tokenVal);
  }
})();

// CSRF Token Helper
window.getCsrfToken = function() {
  const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
  if (cookie) return cookie.split('=')[1];
  const input = document.querySelector('[name=csrfmiddlewaretoken]');
  return input ? input.value : '';
};

// Toast Notification System (Clean Light Design)
window.showToast = function(message, type = 'success') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed top-5 right-5 z-50 flex flex-col gap-2 pointer-events-none';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  const isError = type === 'error';
  const isInfo = type === 'info';

  toast.className = `pointer-events-auto flex items-center gap-3 px-5 py-3.5 rounded-2xl border text-xs font-bold shadow-pebble transition-all duration-300 transform translate-y-[-10px] opacity-0 ${
    isError 
      ? 'bg-terracotta-50 text-terracotta-700 border-terracotta-200' 
      : isInfo 
      ? 'bg-sage-50 text-sage-700 border-sage-200' 
      : 'bg-[#FFFDF9] text-charcoal-900 border-botanical-200 shadow-pebble'
  }`;

  const icon = isError ? 'fa-exclamation-circle text-terracotta-500' : isInfo ? 'fa-info-circle text-sage-500' : 'fa-leaf text-botanical-600';
  toast.innerHTML = `<i class="fas ${icon} text-sm"></i> <span class="leading-relaxed">${message}</span>`;
  container.appendChild(toast);

  // Animate In
  setTimeout(() => {
    toast.classList.remove('translate-y-[-10px]', 'opacity-0');
  }, 10);

  // Animate Out & Remove
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-[-10px]');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
};

// Bookmark Toggle Action
window.toggleBookmark = async function(resourceId, e) {
  if (e) e.stopPropagation();
  try {
    const token = localStorage.getItem('accessToken');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': window.getCsrfToken()
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`/api/resources/${resourceId}/bookmark/`, {
      method: 'POST',
      headers: headers
    });

    if (res.status === 401) {
      window.showToast('Please login to bookmark resources', 'error');
      return;
    }

    const data = await res.json();
    const btn = document.querySelector(`[data-bookmark-btn="${resourceId}"]`);
    if (btn) {
      if (data.bookmarked) {
        btn.innerHTML = '<i class="fas fa-bookmark text-violet-600 text-xs"></i> <span class="text-violet-600 font-bold">Saved</span>';
        window.showToast('Added to bookmarks', 'success');
      } else {
        btn.innerHTML = '<i class="far fa-bookmark text-xs"></i> <span>Save Bookmark</span>';
        window.showToast('Removed from bookmarks', 'info');
      }
    }
  } catch (err) {
    console.error('Bookmark toggle error:', err);
    window.showToast('Failed to update bookmark', 'error');
  }
};

// Download Resource Action
window.downloadResource = async function(resourceId, e) {
  if (e) e.stopPropagation();
  try {
    const token = localStorage.getItem('accessToken');
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': window.getCsrfToken()
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`/api/resources/${resourceId}/download/`, {
      method: 'POST',
      headers: headers
    });

    if (res.ok) {
      const data = await res.json();
      const countEl = document.querySelector(`[data-download-count="${resourceId}"]`);
      if (countEl) {
        let current = parseInt(countEl.innerText.replace(/[^\d]/g, '')) || 0;
        countEl.innerText = `${current + 1}`;
      }
      window.open(data.download_url, '_blank');
      window.showToast('Download starting...', 'success');
    } else {
      window.showToast('Failed to trigger download', 'error');
    }
  } catch (err) {
    console.error('Download error:', err);
    window.showToast('Failed to trigger download', 'error');
  }
};
