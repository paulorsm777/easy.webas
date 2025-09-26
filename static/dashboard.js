// Dashboard JavaScript functionality

let executionChart = null;

function initializeCharts(data) {
  // Initialize execution trends chart
  initializeExecutionChart(data.analytics.hourly_stats);
}

function initializeExecutionChart(hourlyStats) {
  const ctx = document.getElementById("executionChart");
  if (!ctx) return;

  // Prepare data
  const hours = hourlyStats.map((stat) => {
    const date = new Date(stat.hour);
    return date.getHours() + ":00";
  });

  const requests = hourlyStats.map((stat) => stat.requests);
  const successes = hourlyStats.map((stat) => stat.successes);
  const failures = hourlyStats.map((stat) => stat.failures);

  // Destroy existing chart if it exists
  if (executionChart) {
    executionChart.destroy();
  }

  executionChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: hours,
      datasets: [
        {
          label: "Total Requests",
          data: requests,
          borderColor: "#007bff",
          backgroundColor: "rgba(0, 123, 255, 0.1)",
          fill: true,
          tension: 0.4,
        },
        {
          label: "Successful",
          data: successes,
          borderColor: "#28a745",
          backgroundColor: "rgba(40, 167, 69, 0.1)",
          fill: false,
          tension: 0.4,
        },
        {
          label: "Failed",
          data: failures,
          borderColor: "#dc3545",
          backgroundColor: "rgba(220, 53, 69, 0.1)",
          fill: false,
          tension: 0.4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            stepSize: 1,
          },
        },
      },
      plugins: {
        legend: {
          position: "top",
        },
        tooltip: {
          mode: "index",
          intersect: false,
        },
      },
      interaction: {
        mode: "nearest",
        axis: "x",
        intersect: false,
      },
    },
  });
}

// Utility functions
function formatDuration(seconds) {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = (seconds % 60).toFixed(0);
    return `${minutes}m ${remainingSeconds}s`;
  } else {
    const hours = Math.floor(seconds / 3600);
    const remainingMinutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${remainingMinutes}m`;
  }
}

function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
}

function getStatusIcon(status) {
  switch (status) {
    case "completed":
      return '<i class="fas fa-check-circle text-success"></i>';
    case "failed":
      return '<i class="fas fa-times-circle text-danger"></i>';
    case "running":
      return '<i class="fas fa-play-circle text-primary"></i>';
    case "queued":
      return '<i class="fas fa-clock text-secondary"></i>';
    case "timeout":
      return '<i class="fas fa-hourglass-end text-warning"></i>';
    default:
      return '<i class="fas fa-question-circle text-muted"></i>';
  }
}

function getStatusBadgeClass(status) {
  switch (status) {
    case "completed":
      return "bg-success";
    case "failed":
      return "bg-danger";
    case "running":
      return "bg-primary";
    case "queued":
      return "bg-secondary";
    case "timeout":
      return "bg-warning";
    default:
      return "bg-muted";
  }
}

// Real-time updates
function updateLastUpdateTime() {
  const now = new Date();
  const timeString = now.toLocaleString();
  const lastUpdateElement = document.getElementById("lastUpdate");
  if (lastUpdateElement) {
    lastUpdateElement.textContent = timeString;
  }
}

// Progress bar animation
function animateProgressBar(element, targetWidth) {
  if (!element) return;

  const currentWidth = parseFloat(element.style.width) || 0;
  const increment = (targetWidth - currentWidth) / 20;

  let currentStep = 0;
  const animate = () => {
    if (currentStep < 20) {
      const newWidth = currentWidth + increment * currentStep;
      element.style.width = `${Math.min(newWidth, targetWidth)}%`;
      currentStep++;
      requestAnimationFrame(animate);
    }
  };

  animate();
}

// Notification system
function showNotification(message, type = "info", duration = 5000) {
  const container = document.createElement("div");
  container.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
  container.style.cssText =
    "top: 20px; right: 20px; z-index: 1050; min-width: 300px;";

  container.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

  document.body.appendChild(container);

  // Auto remove after duration
  setTimeout(() => {
    if (container.parentNode) {
      container.remove();
    }
  }, duration);
}

// Error handling
function handleApiError(error) {
  console.error("API Error:", error);
  showNotification(
    '<i class="fas fa-exclamation-triangle me-2"></i>Failed to fetch latest data. Check your connection.',
    "warning",
  );
}

// Auto-refresh with exponential backoff
let refreshAttempts = 0;
const maxRefreshAttempts = 5;

function refreshDashboard() {
  fetch(window.location.href)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      refreshAttempts = 0; // Reset on success
      location.reload();
    })
    .catch((error) => {
      refreshAttempts++;
      const delay = Math.min(1000 * Math.pow(2, refreshAttempts), 30000); // Max 30s delay

      handleApiError(error);

      if (refreshAttempts < maxRefreshAttempts) {
        setTimeout(refreshDashboard, delay);
      } else {
        showNotification(
          '<i class="fas fa-wifi me-2"></i>Dashboard auto-refresh disabled due to connection issues.',
          "danger",
          10000,
        );
      }
    });
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", function () {
  // Update last update time
  updateLastUpdateTime();

  // Add click handlers for interactive elements
  document.querySelectorAll('[data-toggle="modal"]').forEach((element) => {
    element.addEventListener("click", function (e) {
      e.preventDefault();
      // Handle modal opening
    });
  });

  // Add hover effects for cards
  document.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("mouseenter", function () {
      this.style.transform = "translateY(-2px)";
    });

    card.addEventListener("mouseleave", function () {
      this.style.transform = "translateY(0)";
    });
  });

  // Copy to clipboard functionality
  document.querySelectorAll("[data-copy]").forEach((element) => {
    element.addEventListener("click", function () {
      const text = this.getAttribute("data-copy");
      navigator.clipboard.writeText(text).then(() => {
        showNotification("Copied to clipboard!", "success", 2000);
      });
    });
  });
});

// Keyboard shortcuts
document.addEventListener("keydown", function (e) {
  // Ctrl/Cmd + R: Force refresh
  if ((e.ctrlKey || e.metaKey) && e.key === "r") {
    e.preventDefault();
    location.reload(true);
  }

  // Escape: Close any open modals
  if (e.key === "Escape") {
    const modals = document.querySelectorAll(".modal.show");
    modals.forEach((modal) => {
      const bsModal = bootstrap.Modal.getInstance(modal);
      if (bsModal) {
        bsModal.hide();
      }
    });
  }
});

// Cleanup on page unload
window.addEventListener("beforeunload", function () {
  if (executionChart) {
    executionChart.destroy();
  }
});
