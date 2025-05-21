/**
 * Pi Auto Transaction Tool - High Frequency Edition
 * Frontend JavaScript for handling real-time transaction management
 */

// Configuration
const DEFAULT_INTERVAL_MS = 1; // Default to 1ms instead of 5000ms
const MIN_INTERVAL_MS = 1; // Minimum allowed interval
const MAX_TRANSACTIONS_DISPLAY = 100; // Max transactions to display
let transactionTimer = null;
let statusPollTimer = null;
let performanceChartInstance = null;

// DOM elements
const walletForm = document.getElementById('walletForm');
const connectButton = document.getElementById('connectButton');
const disconnectButton = document.getElementById('disconnectButton');
const startButton = document.getElementById('startButton');
const stopButton = document.getElementById('stopButton');
const balanceDisplay = document.getElementById('balanceDisplay');
const balanceBar = document.getElementById('balanceBar');
const connectionStatus = document.getElementById('connectionStatus');
const statusMessage = document.getElementById('statusMessage');
const transactionsTableBody = document.getElementById('transactionsTableBody');
const refreshButton = document.getElementById('refreshButton');
const txStatusBadge = document.getElementById('txStatusBadge');
const timingInfo = document.getElementById('timingInfo');
const currentIntervalDisplay = document.getElementById('currentIntervalDisplay');
const scheduledTimeDisplay = document.getElementById('scheduledTimeDisplay');
const keyTypeIndicator = document.getElementById('keyTypeIndicator');
const transactionInterval = document.getElementById('transactionInterval');
const scheduledTime = document.getElementById('scheduledTime');
const performanceStatsDiv = document.getElementById('performanceStats');
const driftChart = document.getElementById('driftChart');

// Initialize tooltips and popovers
document.addEventListener('DOMContentLoaded', () => {
  // Initialize bootstrap tooltips
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Initialize popovers
  const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
  popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl);
  });

  // Set default interval to 1ms
  if (transactionInterval) {
    transactionInterval.value = DEFAULT_INTERVAL_MS;
  }
});

// Toggle password visibility
document.querySelectorAll('.toggle-password').forEach(button => {
  button.addEventListener('click', function() {
    const targetId = this.getAttribute('data-target');
    const passwordInput = document.getElementById(targetId);
    const icon = this.querySelector('i');
    
    if (passwordInput.type === 'password') {
      passwordInput.type = 'text';
      icon.classList.remove('fa-eye');
      icon.classList.add('fa-eye-slash');
    } else {
      passwordInput.type = 'password';
      icon.classList.remove('fa-eye-slash');
      icon.classList.add('fa-eye');
    }
  });
});

// Wallet connection
walletForm.addEventListener('submit', async function(e) {
  e.preventDefault();
  
  // Show loading state
  connectButton.disabled = true;
  connectButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting...';
  
  const formData = {
    sender_secret: document.getElementById('senderSecret').value,
    sender_public: document.getElementById('senderPublic').value,
    receiver_address: document.getElementById('receiverAddress').value,
    amount: document.getElementById('amount').value,
    network: document.getElementById('network').value
  };
  
  try {
    const response = await fetch('/api/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });
    
    const data = await response.json();
    
    if (data.success) {
      // Update UI for successful connection
      updateConnectionStatus('success', data.message);
      updateBalance(data.balance);
      
      // Enable transaction controls
      startButton.disabled = false;
      disconnectButton.disabled = false;
      
      // Disable form fields
      toggleFormFields(true);
      
      // Update key type indicator
      keyTypeIndicator.textContent = data.using_default_key ? 
        "Using Default Key" : "Using Custom Key";
      keyTypeIndicator.className = data.using_default_key ? 
        "badge bg-warning" : "badge bg-success";
        
      // Auto-poll for balance updates
      startBalanceUpdates();
    } else {
      updateConnectionStatus('danger', data.message);
    }
  } catch (error) {
    updateConnectionStatus('danger', `Connection failed: ${error.message}`);
  } finally {
    connectButton.disabled = false;
    connectButton.innerHTML = '<i class="fa-solid fa-link"></i> Connect Wallet';
  }
});

// Disconnect wallet
disconnectButton.addEventListener('click', function() {
  // Clear session data (client-side only)
  stopTransaction();
  stopBalanceUpdates();
  stopStatusPolling();
  
  // Reset UI
  balanceDisplay.textContent = '-- π';
  balanceBar.style.width = '0%';
  connectionStatus.className = 'alert alert-secondary';
  connectionStatus.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> Wallet not connected';
  
  // Disable transaction controls
  startButton.disabled = true;
  stopButton.disabled = true;
  disconnectButton.disabled = true;
  
  // Enable form fields
  toggleFormFields(false);
  
  // Clear key type indicator
  keyTypeIndicator.textContent = "No wallet connected";
  keyTypeIndicator.className = "badge bg-secondary";
  
  // Clear transaction table
  transactionsTableBody.innerHTML = '<tr><td colspan="5" class="text-center">No transactions yet</td></tr>';
  txStatusBadge.textContent = 'Inactive';
  txStatusBadge.className = 'badge bg-info ms-2';
  
  // Hide performance stats
  if (timingInfo) timingInfo.classList.add('d-none');
  if (performanceStatsDiv) performanceStatsDiv.classList.add('d-none');
  
  // Destroy chart if it exists
  if (performanceChartInstance) {
    performanceChartInstance.destroy();
    performanceChartInstance = null;
  }
});

// Start transaction bot
startButton.addEventListener('click', async function() {
  const interval = parseInt(transactionInterval.value) || DEFAULT_INTERVAL_MS;
  const scheduled = scheduledTime.value;
  
  // Validate interval
  if (interval < MIN_INTERVAL_MS) {
    alert(`Interval must be at least ${MIN_INTERVAL_MS}ms`);
    transactionInterval.value = MIN_INTERVAL_MS;
    return;
  }
  
  // Update UI
  startButton.disabled = true;
  startButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Starting...';
  
  try {
    const response = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transaction_interval: interval,
        scheduled_time: scheduled
      })
    });
    
    const data = await response.json();
    
    if (data.success) {
      // Update UI for running state
      updateStatusMessage('success', data.message);
      txStatusBadge.textContent = 'Active';
      txStatusBadge.className = 'badge bg-success ms-2';
      
      // Enable/disable buttons
      stopButton.disabled = false;
      startButton.disabled = true;
      
      // Show timing info
      if (timingInfo) {
        timingInfo.classList.remove('d-none');
        currentIntervalDisplay.textContent = `${interval}ms`;
        scheduledTimeDisplay.textContent = scheduled ? new Date(scheduled).toLocaleString() : 'Immediate';
      }
      
      // Start polling for status updates
      startStatusPolling();
    } else {
      updateStatusMessage('danger', data.message);
      startButton.disabled = false;
    }
  } catch (error) {
    updateStatusMessage('danger', `Error starting transaction bot: ${error.message}`);
    startButton.disabled = false;
  } finally {
    startButton.innerHTML = '<i class="fa-solid fa-play"></i> START SENDING PI';
  }
});

// Stop transaction bot
stopButton.addEventListener('click', async function() {
  await stopTransaction();
});

// Refresh transaction history
refreshButton.addEventListener('click', async function() {
  refreshButton.innerHTML = '<i class="fa-solid fa-arrows-rotate fa-spin"></i>';
  await fetchTransactionHistory();
  refreshButton.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Refresh';
});

// Helper Functions
async function stopTransaction() {
  stopButton.disabled = true;
  stopButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Stopping...';
  
  try {
    const response = await fetch('/api/stop', {
      method: 'POST'
    });
    
    const data = await response.json();
    
    if (data.success) {
      updateStatusMessage('info', data.message);
      txStatusBadge.textContent = 'Stopped';
      txStatusBadge.className = 'badge bg-warning ms-2';
      
      // Update buttons
      startButton.disabled = false;
      stopButton.disabled = true;
      
      // Stop polling
      stopStatusPolling();
    } else {
      updateStatusMessage('warning', data.message);
    }
  } catch (error) {
    updateStatusMessage('danger', `Error stopping transaction bot: ${error.message}`);
  } finally {
    stopButton.innerHTML = '<i class="fa-solid fa-stop"></i> STOP TRANSACTIONS';
  }
}

function updateConnectionStatus(type, message) {
  connectionStatus.className = `alert alert-${type}`;
  connectionStatus.innerHTML = `<i class="fa-solid fa-${type === 'success' ? 'check-circle' : 'circle-exclamation'}"></i> ${message}`;
}

function updateStatusMessage(type, message) {
  if (statusMessage) {
    statusMessage.className = `alert alert-${type} mt-3`;
    statusMessage.innerHTML = message;
    statusMessage.classList.remove('d-none');
    
    // Auto-hide success messages after 5 seconds
    if (type === 'success') {
      setTimeout(() => {
        statusMessage.classList.add('d-none');
      }, 5000);
    }
  }
}

function updateBalance(balance) {
  if (balanceDisplay) {
    balanceDisplay.textContent = `${balance} π`;
    
    // Update progress bar (assuming max balance of 100 Pi for visual purposes)
    const balanceValue = parseFloat(balance);
    const percentage = Math.min(balanceValue, 100);
    balanceBar.style.width = `${percentage}%`;
    
    // Color coding based on balance
    if (balanceValue < 1) {
      balanceBar.className = 'progress-bar bg-danger';
    } else if (balanceValue < 10) {
      balanceBar.className = 'progress-bar bg-warning';
    } else {
      balanceBar.className = 'progress-bar bg-success';
    }
  }
}

function toggleFormFields(disabled) {
  document.getElementById('senderSecret').disabled = disabled;
  document.getElementById('senderPublic').disabled = disabled;
  document.getElementById('receiverAddress').disabled = disabled;
  document.getElementById('amount').disabled = disabled;
  document.getElementById('network').disabled = disabled;
  connectButton.disabled = disabled;
}

async function fetchTransactionHistory() {
  try {
    const response = await fetch('/api/transactions');
    const data = await response.json();
    
    if (data.transactions && data.transactions.length > 0) {
      updateTransactionTable(data.transactions);
    }
  } catch (error) {
    console.error('Error fetching transactions:', error);
  }
}

function updateTransactionTable(transactions) {
  if (!transactionsTableBody) return;
  
  // Clear table
  transactionsTableBody.innerHTML = '';
  
  // Add transactions, newest first
  transactions.slice().reverse().forEach(tx => {
    const row = document.createElement('tr');
    
    // Status class
    let statusClass = 'bg-secondary';
    let statusIcon = 'question-circle';
    
    if (tx.status === 'Success') {
      statusClass = 'bg-success';
      statusIcon = 'check-circle';
    } else if (tx.status === 'Pending') {
      statusClass = 'bg-warning';
      statusIcon = 'clock';
    } else if (tx.status === 'Error') {
      statusClass = 'bg-danger';
      statusIcon = 'exclamation-circle';
    }
    
    // Create cells
    row.innerHTML = `
      <td>${tx.timestamp}</td>
      <td>${tx.amount} π</td>
      <td><span class="badge ${statusClass}"><i class="fa-solid fa-${statusIcon}"></i> ${tx.status}</span></td>
      <td>
        ${tx.hash !== 'Failed' && tx.hash !== 'Unknown' ? 
          `<a href="https://explorer.minepi.com/tx/${tx.hash}" target="_blank" class="text-truncate" title="${tx.hash}">
            ${tx.hash.substring(0, 8)}...${tx.hash.substring(tx.hash.length - 8)}
           </a>` : 
          `<span class="text-muted">${tx.hash}</span>`
        }
        ${tx.error ? `<div class="small text-danger">${tx.error}</div>` : ''}
        ${tx.processing_time_ms ? `<div class="small text-muted">${tx.processing_time_ms}ms</div>` : ''}
      </td>
      <td>
        ${tx.verified ? 
          '<i class="fa-solid fa-check text-success"></i> Verified' : 
          '<i class="fa-solid fa-question text-muted"></i> Unverified'
        }
      </td>
    `;
    
    transactionsTableBody.appendChild(row);
  });
  
  // If no transactions
  if (transactions.length === 0) {
    transactionsTableBody.innerHTML = '<tr><td colspan="5" class="text-center">No transactions yet</td></tr>';
  }
}

function startBalanceUpdates() {
  // Check balance every 10 seconds
  if (transactionTimer) clearInterval(transactionTimer);
  transactionTimer = setInterval(fetchBalance, 10000);
  fetchBalance(); // Initial fetch
}

function stopBalanceUpdates() {
  if (transactionTimer) {
    clearInterval(transactionTimer);
    transactionTimer = null;
  }
}

async function fetchBalance() {
  try {
    const response = await fetch('/api/balance');
    const data = await response.json();
    
    if (data.success) {
      updateBalance(data.balance);
    }
  } catch (error) {
    console.error('Error fetching balance:', error);
  }
}

function startStatusPolling() {
  // Poll status every 1 second
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(pollStatus, 1000);
  pollStatus(); // Initial poll
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
}

async function pollStatus() {
  try {
    const response = await fetch('/api/status');
    const data = await response.json();
    
    // Update transaction table
    if (data.transactions && data.transactions.length > 0) {
      updateTransactionTable(data.transactions);
    }
    
    // Update performance stats if available
    if (data.performance && Object.keys(data.performance).length > 0) {
      updatePerformanceStats(data.performance);
    }
    
    // Check if still running
    if (!data.running) {
      txStatusBadge.textContent = 'Inactive';
      txStatusBadge.className = 'badge bg-info ms-2';
      startButton.disabled = false;
      stopButton.disabled = true;
      stopStatusPolling();
    }
  } catch (error) {
    console.error('Error polling status:', error);
  }
}

function updatePerformanceStats(performance) {
  // Make sure performance stats div exists
  if (!performanceStatsDiv) return;
  
  // Show the stats container
  performanceStatsDiv.classList.remove('d-none');
  
  // Update performance metrics
  performanceStatsDiv.innerHTML = `
    <h5 class="mb-3"><i class="fa-solid fa-gauge-high"></i> Performance Metrics</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <div class="card bg-light bg-opacity-10">
          <div class="card-body p-3">
            <h6 class="card-title">Timing Precision</h6>
            <p class="mb-1"><strong>Avg Drift:</strong> <span class="${performance.avg_drift_ms > 5 ? 'text-warning' : 'text-success'}">${performance.avg_drift_ms}ms</span></p>
            <p class="mb-1"><strong>Min/Max Drift:</strong> ${performance.min_drift_ms}ms / ${performance.max_drift_ms}ms</p>
            <p class="mb-0"><strong>Timing Stability:</strong> 
              <span class="${performance.timing_stability < 80 ? 'text-warning' : 'text-success'}">
                ${performance.timing_stability}%
              </span>
            </p>
          </div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card bg-light bg-opacity-10">
          <div class="card-body p-3">
            <h6 class="card-title">Transaction Metrics</h6>
            <p class="mb-1"><strong>Transaction Count:</strong> ${performance.tx_count}</p>
            <p class="mb-1"><strong>Success Rate:</strong> 
              <span class="${performance.success_rate < 80 ? 'text-warning' : 'text-success'}">
                ${performance.success_rate}%
              </span>
            </p>
            <p class="mb-0"><strong>Avg Processing:</strong> ${performance.avg_processing_ms}ms</p>
          </div>
        </div>
      </div>
    </div>
  `;
  
  // Update performance chart
  updatePerformanceChart(performance);
}

function updatePerformanceChart(performance) {
  // Only update chart if we have drift samples and the chart element exists
  if (!performance.drift_samples || !driftChart) return;
  
  // If chart already exists, destroy it
  if (performanceChartInstance) {
    performanceChartInstance.destroy();
  }
  
  // Prepare data
  const labels = performance.drift_samples.map((_, i) => `Tx ${i+1}`);
  const driftData = performance.drift_samples;
  const processingData = performance.processing_samples || [];
  
  // Create Chart
  performanceChartInstance = new Chart(driftChart, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Timing Drift (ms)',
          data: driftData,
          borderColor: '#8b5cf6',
          backgroundColor: 'rgba(139, 92, 246, 0.1)',
          borderWidth: 2,
          tension: 0.2,
          fill: true
        },
        {
          label: 'Processing Time (ms)',
          data: processingData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          borderWidth: 2,
          tension: 0.2,
          fill: true,
          hidden: processingData.length === 0
        }
      ]
    },
    options: {
      responsive: true,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: 'Milliseconds'
          },
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          }
        },
        x: {
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          }
        }
      },
      plugins: {
        legend: {
          position: 'top',
        },
        title: {
          display: true,
          text: 'Transaction Timing Performance'
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `${context.dataset.label}: ${context.parsed.y.toFixed(2)}ms`;
            }
          }
        }
      }
    }
  });
}