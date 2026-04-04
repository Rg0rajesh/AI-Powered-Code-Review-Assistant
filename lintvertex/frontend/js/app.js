/* ============================================================
   LintVertex – Shared JavaScript Utilities
   API client, auth helpers, theme, toasts
   ============================================================ */

// ── API Base URL ──────────────────────────────────────────────
// If deploying frontend on Vercel AND backend on Render:
// Change the URL below to your Render URL (e.g. https://lintvertex-api.onrender.com)
const API_BASE = window.location.origin.includes("vercel.app")
  ? "https://lintvertex-backend.onrender.com"
  : window.location.origin;

// ── Storage Keys ──────────────────────────────────────────────
const STORAGE_KEYS = {
  TOKEN: "lv_token",
  USER: "lv_user",
  THEME: "lv_theme",
};

// ── Auth Helpers ──────────────────────────────────────────────
const Auth = {
  getToken() {
    return localStorage.getItem(STORAGE_KEYS.TOKEN);
  },
  getUser() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEYS.USER));
    } catch { return null; }
  },
  setSession(token, user) {
    localStorage.setItem(STORAGE_KEYS.TOKEN, token);
    localStorage.setItem(STORAGE_KEYS.USER, JSON.stringify(user));
  },
  clearSession() {
    localStorage.removeItem(STORAGE_KEYS.TOKEN);
    localStorage.removeItem(STORAGE_KEYS.USER);
  },
  isLoggedIn() {
    return !!this.getToken();
  },
  isAdmin() {
    const user = this.getUser();
    return user && user.role === "admin";
  },
  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.href = "/login.html";
      return false;
    }
    return true;
  },
  requireAdmin() {
    if (!this.isAdmin()) {
      window.location.href = "/dashboard.html";
      return false;
    }
    return true;
  },
};

// ── API Client ────────────────────────────────────────────────
const API = {
  async request(method, path, body = null, isFormData = false) {
    const headers = {};
    const token = Auth.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (!isFormData && body) headers["Content-Type"] = "application/json";

    const opts = {
      method,
      headers,
      body: body
        ? isFormData ? body : JSON.stringify(body)
        : null,
    };

    const res = await fetch(`${API_BASE}${path}`, opts);
    const data = await res.json().catch(() => ({}));

    if (res.status === 401) {
      Auth.clearSession();
      window.location.href = "/login.html";
    }

    return { ok: res.ok, status: res.status, data };
  },

  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },
  put(path, body) { return this.request("PUT", path, body); },
  delete(path) { return this.request("DELETE", path); },
  postForm(path, formData) { return this.request("POST", path, formData, true); },
  putForm(path, formData) { return this.request("PUT", path, formData, true); },
};

// ── Toast Notifications ───────────────────────────────────────
const Toast = {
  container: null,

  init() {
    if (!this.container) {
      this.container = document.createElement("div");
      this.container.id = "toast-container";
      document.body.appendChild(this.container);
    }
  },

  show(message, type = "info", duration = 4000) {
    this.init();
    const icons = { success: "✓", error: "✗", warning: "⚠", info: "ℹ" };
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || "ℹ"}</span><span>${message}</span>`;
    this.container.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = "toastIn 0.3s ease reverse";
      setTimeout(() => toast.remove(), 300);
    }, duration);
  },

  success(msg) { this.show(msg, "success"); },
  error(msg) { this.show(msg, "error"); },
  warning(msg) { this.show(msg, "warning"); },
  info(msg) { this.show(msg, "info"); },
};

// ── Theme Manager ─────────────────────────────────────────────
const Theme = {
  init() {
    const saved = localStorage.getItem(STORAGE_KEYS.THEME);
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
    this.apply(theme);

    // Listen for system changes
    window.matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", (e) => {
        if (!localStorage.getItem(STORAGE_KEYS.THEME)) {
          this.apply(e.matches ? "dark" : "light");
        }
      });
  },

  apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEYS.THEME, theme);

    // Update all toggle buttons
    document.querySelectorAll(".toggle-track").forEach((el) => {
      el.classList.toggle("active", theme === "dark");
    });

    document.querySelectorAll(".theme-label").forEach((el) => {
      el.textContent = theme === "dark" ? "🌙" : "☀️";
    });
  },

  toggle() {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    this.apply(current === "dark" ? "light" : "dark");
  },

  get current() {
    return document.documentElement.getAttribute("data-theme") || "light";
  },
};

// ── Navigation helpers ────────────────────────────────────────
function populateUserNav() {
  const user = Auth.getUser();

  // Logged in/out elements visibility
  document.querySelectorAll(".logged-in-only").forEach((el) => {
    el.style.display = Auth.isLoggedIn() ? "" : "none";
  });
  document.querySelectorAll(".logged-out-only").forEach((el) => {
    el.style.display = Auth.isLoggedIn() ? "none" : "";
  });

  // Global notification check
  checkNotifications();

  if (!user) return;

  // Username in nav/sidebar
  document.querySelectorAll("[data-user-name]").forEach((el) => {
    el.textContent = user.username;
  });

  // Role display
  const roleEl = document.getElementById("sidebarRole");
  if (roleEl) roleEl.textContent = user.role === 'admin' ? 'Admin' : 'Developer';

  // Avatar handling (Global)
  const avContainers = document.querySelectorAll("#sidebarAvatar, [data-user-avatar]");
  avContainers.forEach(container => {
    if (user.profile_image) {
      // If it's an img tag
      if (container.tagName === 'IMG') {
        container.src = user.profile_image;
        container.style.display = "block";
      } else {
        // If it's a div container
        container.innerHTML = `<img src="${user.profile_image}" style="width:100%;height:100%;object-fit:cover" />`;
      }
    } else {
      container.textContent = user.username[0].toUpperCase();
    }
  });

  // Admin link visibility
  if (user.role === "admin") {
    document.querySelectorAll(".admin-only").forEach((el) => {
      el.style.display = "";
    });
  }
}

/**
 * Global Notifications Check
 * Fetches unread count and updates any notification bells in the navbar.
 */
async function checkNotifications() {
  if (!Auth.isLoggedIn()) return;

  try {
    const { ok, data } = await API.get("/api/notifications/count");
    if (ok) {
      updateNotificationBells(data.unread_count);
    }
  } catch (e) {
    console.warn("Notification check failed:", e);
  }
}

/**
 * Updates all notification bell icons in the DOM.
 * Expects elements with class .notif-bell or [data-notif-count].
 */
function updateNotificationBells(count) {
  document.querySelectorAll(".notif-badge").forEach((el) => {
    if (count > 0) {
      el.textContent = count > 99 ? "99+" : count;
      el.style.display = "flex";
      el.classList.add("pulse");
    } else {
      el.style.display = "none";
      el.classList.remove("pulse");
    }
  });

  // Use for aria-labels or title attributes
  document.querySelectorAll("[data-notif-count]").forEach((el) => {
    el.setAttribute("data-notif-count", count);
    el.title = count > 0 ? `You have ${count} unread notifications` : "No new notifications";
  });
}

// ── Format Helpers ────────────────────────────────────────────
function formatDate(isoString) {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  }).format(new Date(isoString));
}

function formatRelative(isoString) {
  if (!isoString) return "—";
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function escapeHtml(str) {
  const el = document.createElement("div");
  el.textContent = str;
  return el.innerHTML;
}

// ── Tabs ──────────────────────────────────────────────────────
function initTabs(containerSelector = ".tabs") {
  document.querySelectorAll(containerSelector).forEach((tabs) => {
    tabs.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tab;

        // Deactivate all
        tabs.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));

        btn.classList.add("active");
        const panel = document.getElementById(`tab-${target}`);
        if (panel) panel.classList.add("active");
      });
    });
  });
}

// ── Score Ring ────────────────────────────────────────────────
function renderScoreRing(containerId, score, size = 120) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const r = (size / 2) - 12;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (score / 100) * circumference;

  const color = score >= 85 ? "var(--grade-a)"
    : score >= 70 ? "var(--grade-b)"
      : score >= 55 ? "var(--grade-c)"
        : score >= 40 ? "var(--grade-d)"
          : "var(--grade-f)";

  container.innerHTML = `
    <div class="score-ring" style="width:${size}px;height:${size}px;">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}"
          fill="none" stroke="var(--border)" stroke-width="8"/>
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}"
          fill="none" stroke="${color}" stroke-width="8"
          stroke-dasharray="${circumference}"
          stroke-dashoffset="${offset}"
          stroke-linecap="round"
          style="transition: stroke-dashoffset 1s ease"/>
      </svg>
      <div class="score-ring-value" style="font-size:${size / 5}px">${score}</div>
    </div>`;
}

// ── Init (runs on every page) ─────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  Theme.init();
  populateUserNav();
  initTabs();

  // Bind theme toggle buttons
  document.querySelectorAll(".toggle-track, [data-theme-toggle]").forEach((el) => {
    el.addEventListener("click", () => Theme.toggle());
  });

  // Logout buttons
  document.querySelectorAll("[data-logout]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      Auth.clearSession();
      window.location.href = "/index.html";
    });
  });
});


// ════════════════════════════════════════════════════════════════
// TERMS & CONDITIONS GATE
// Call checkTermsGate() on any protected page (dashboard, analyze, etc.)
// It checks /api/terms/status and redirects to /terms.html if needed.
// ════════════════════════════════════════════════════════════════

async function checkTermsGate() {
  if (!Auth.isLoggedIn()) return;

  // Don't gate on the terms page itself or auth pages
  const exempt = ["/terms.html", "/login.html", "/signup.html", "/index.html",
    "/about.html", "/admin-login.html"];
  if (exempt.some(p => window.location.pathname.endsWith(p))) return;

  try {
    const { ok, data } = await API.get("/api/terms/status");
    if (ok && data.needs_acceptance) {
      // Store redirect target so terms page can send user back
      sessionStorage.setItem("terms_redirect", window.location.href);
      window.location.href = "/terms.html";
    }
  } catch (e) {
    // Network failure — don't block user, fail open
    console.warn("Terms check failed (network):", e);
  }
}

// Auto-run gate on every page that has Auth.requireAuth()
// Pages call Auth.requireAuth() which we now augment:
const _originalRequireAuth = Auth.requireAuth.bind(Auth);
Auth.requireAuth = function () {
  const result = _originalRequireAuth();
  if (result) checkTermsGate(); // runs async, non-blocking
  return result;
};
