// ---\
// --- APPROVALS.JS ---\
// ---\
// Controls logic for the Approval Module feed.

let currentRequests = [];
let selectedRequestId = null;
let pendingAction = null; // 'Approved' or 'Rejected'

document.addEventListener('DOMContentLoaded', () => {
    fetchFeed();
});

/**
 * Fetch and Render Feed
 */
async function fetchFeed() {
    const container = document.getElementById('approval-feed');
    const countBadge = document.getElementById('pending-count');
    
    // Simple loading state if empty
    if (!container.children.length || container.children[0].classList.contains('animate-pulse')) {
        // Keep skeleton if initial load
    } else {
        // Subtle refresh indicator
        container.style.opacity = '0.5';
    }

    try {
        const res = await fetch('/api/approvals/feed');
        if (!res.ok) throw new Error("Failed to load feed");
        const data = await res.json();
        
        currentRequests = data;
        countBadge.textContent = data.length;
        renderFeed(data);
    } catch (e) {
        console.error(e);
        showMessage("Error loading feed. Pull to refresh.", "error");
    } finally {
        container.style.opacity = '1';
    }
}

/**
 * Render Cards
 */
function renderFeed(items) {
    const container = document.getElementById('approval-feed');
    const template = document.getElementById('card-template');
    container.innerHTML = '';

    if (items.length === 0) {
        container.innerHTML = `
            <div class="text-center py-12">
                <div class="bg-slate-50 rounded-full w-16 h-16 flex items-center justify-center mx-auto mb-4">
                    <svg class="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                </div>
                <h3 class="text-slate-800 font-bold">All Caught Up!</h3>
                <p class="text-slate-500 text-sm mt-1">No pending approvals requiring your attention.</p>
            </div>
        `;
        return;
    }

    items.forEach(item => {
        const clone = template.content.cloneNode(true);
        const card = clone.querySelector('.approval-card');
        
        // 1. Data Binding
        // Sender Initials
        const details = item.details || {};
        const who = details.who || "Unknown";
        const initials = who.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
        
        card.querySelector('.sender-initials').textContent = initials;
        card.querySelector('.sender-name').textContent = who;
        card.querySelector('.request-type').textContent = item.request_type;
        
        // Risk Logic
        const risk = item.risk_level || 'Medium';
        const riskBadge = card.querySelector('.risk-badge');
        const riskStrip = card.querySelector('.risk-strip');
        
        riskBadge.textContent = `${risk.toUpperCase()} RISK`;
        if (risk === 'High') {
            riskBadge.className = 'risk-badge text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-700 border border-red-200';
            riskStrip.className = 'risk-strip absolute left-0 top-0 bottom-0 w-1.5 bg-red-500';
        } else if (risk === 'Low') {
            riskBadge.className = 'risk-badge text-[10px] font-bold px-2 py-0.5 rounded-full bg-green-100 text-green-700 border border-green-200';
            riskStrip.className = 'risk-strip absolute left-0 top-0 bottom-0 w-1.5 bg-green-500';
        } else {
            // Medium
            riskBadge.className = 'risk-badge text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200';
            riskStrip.className = 'risk-strip absolute left-0 top-0 bottom-0 w-1.5 bg-amber-500';
        }

        // Time
        const date = new Date(item.created_at);
        card.querySelector('.time-ago').textContent = timeAgo(date);

        // Summary
        card.querySelector('.summary-text').textContent = item.summary;

        // Impact (Enhancement)
        if (item.impact) {
            const impactBox = card.querySelector('.impact-box');
            impactBox.classList.remove('hidden');
            impactBox.querySelector('.impact-text').textContent = item.impact;
        }

        // 5W1H Details
        const grid = card.querySelector('.details-grid');
        for (const [key, val] of Object.entries(details)) {
            if (key === 'who') continue; // Already shown
            const row = document.createElement('div');
            row.innerHTML = `<span class="font-bold uppercase text-slate-400 mr-1">${key}:</span> <span class="text-slate-700">${val}</span>`;
            grid.appendChild(row);
        }

        // Actions
        card.querySelector('.action-btn-approve').onclick = () => openActionModal(item.id, 'Approved', risk);
        card.querySelector('.action-btn-reject').onclick = () => openActionModal(item.id, 'Rejected', risk);
        
        // Delete Action
        card.querySelector('.delete-btn').onclick = (e) => {
            e.stopPropagation(); // Prevent detail toggle if clicking delete
            deleteRequest(item.id);
        };

        container.appendChild(card);
    });
}

/**
 * Action Modal Logic
 */
function openActionModal(id, action, risk) {
    selectedRequestId = id;
    pendingAction = action;
    
    const modal = document.getElementById('actionModal');
    const panel = document.getElementById('actionModalPanel');
    const title = document.getElementById('actionModalTitle');
    const text = document.getElementById('actionModalText');
    const btn = document.getElementById('confirmActionBtn');
    const notes = document.getElementById('actionNotes');
    
    notes.value = ''; // Reset notes

    // Configure UI based on Action & Risk
    if (action === 'Approved') {
        title.textContent = "Confirm Approval";
        title.className = "text-lg font-bold text-emerald-700 mb-2";
        btn.className = "flex-1 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg shadow-md transition-colors";
        
        if (risk === 'High') {
            text.innerHTML = `⚠️ <span class="font-bold">High Risk Item.</span> Are you absolutely sure you want to approve this? This action will be logged.`;
        } else {
            text.textContent = "Are you sure you want to approve this request? An email notification will be sent.";
        }
    } else {
        title.textContent = "Confirm Rejection";
        title.className = "text-lg font-bold text-red-700 mb-2";
        btn.className = "flex-1 py-2.5 bg-red-600 hover:bg-red-700 text-white font-bold rounded-lg shadow-md transition-colors";
        text.textContent = "Please provide a reason for rejection (optional but recommended).";
    }

    modal.classList.remove('hidden');
    // Small timeout for fade-in
    setTimeout(() => {
        modal.classList.remove('opacity-0');
        panel.classList.remove('scale-95');
        panel.classList.add('scale-100');
    }, 10);
    
    // Bind Confirm
    btn.onclick = executeAction;
}

function closeActionModal() {
    const modal = document.getElementById('actionModal');
    const panel = document.getElementById('actionModalPanel');
    
    modal.classList.add('opacity-0');
    panel.classList.remove('scale-100');
    panel.classList.add('scale-95');
    
    setTimeout(() => {
        modal.classList.add('hidden');
        selectedRequestId = null;
        pendingAction = null;
    }, 200);
}

/**
 * Execute API Call
 */
async function executeAction() {
    const btn = document.getElementById('confirmActionBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Processing...";
    
    const notes = document.getElementById('actionNotes').value;
    
    try {
        const res = await fetch(`/api/approvals/${selectedRequestId}/action`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ action: pendingAction, notes: notes })
        });
        
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.error || "Action failed");
        
        showMessage(data.message, 'success');
        closeActionModal();
        fetchFeed(); // Refresh list
        
    } catch (e) {
        showMessage(e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

/**
 * Delete Request
 */
async function deleteRequest(id) {
    if (!confirm("Are you sure you want to delete this approval request?")) return;
    
    try {
        const res = await fetch(`/api/approvals/${id}`, {
            method: 'DELETE'
        });
        
        // Handle non-JSON responses (like 404 HTML pages)
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
            throw new Error(`Server returned ${res.status}: ${res.statusText}. Check server logs.`);
        }

        const data = await res.json();
        
        if (!res.ok) {
            throw new Error(data.error || "Delete failed");
        }
        
        showMessage("Request deleted.", "success");
        fetchFeed();
    } catch (e) {
        console.error(e);
        showMessage(e.message, 'error');
    }
}


/**
 * History Modal Logic
 */
function toggleHistoryModal() {
    const modal = document.getElementById('historyModal');
    const panel = document.getElementById('historyPanel');
    
    if (modal.classList.contains('hidden')) {
        modal.classList.remove('hidden');
        loadHistory(); // Load data
        setTimeout(() => panel.classList.remove('translate-x-full'), 10);
    } else {
        panel.classList.add('translate-x-full');
        setTimeout(() => modal.classList.add('hidden'), 300);
    }
}

async function loadHistory() {
    const list = document.getElementById('historyList');
    list.innerHTML = '<p class="text-slate-400 text-sm text-center">Loading history...</p>';
    
    try {
        const res = await fetch('/api/approvals/history');
        const data = await res.json();
        
        list.innerHTML = '';
        if (data.length === 0) {
            list.innerHTML = '<p class="text-slate-400 text-sm text-center">No history yet.</p>';
            return;
        }
        
        data.forEach(item => {
            const div = document.createElement('div');
            div.className = "bg-white p-3 rounded border border-slate-200 shadow-sm opacity-75";
            const statusColor = item.status === 'Approved' ? 'text-emerald-600' : 'text-red-600';
            div.innerHTML = `
                <div class="flex justify-between items-center mb-1">
                    <span class="font-bold text-slate-700 text-sm">${item.summary}</span>
                    <span class="text-xs font-bold ${statusColor}">${item.status.toUpperCase()}</span>
                </div>
                <p class="text-xs text-slate-500">${new Date(item.created_at).toLocaleString()}</p>
            `;
            list.appendChild(div);
        });
    } catch (e) {
        list.innerHTML = '<p class="text-red-400 text-sm text-center">Failed to load history.</p>';
    }
}

// Helper: Time Ago
function timeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    let interval = seconds / 31536000;
    if (interval > 1) return Math.floor(interval) + "y ago";
    interval = seconds / 2592000;
    if (interval > 1) return Math.floor(interval) + "mo ago";
    interval = seconds / 86400;
    if (interval > 1) return Math.floor(interval) + "d ago";
    interval = seconds / 3600;
    if (interval > 1) return Math.floor(interval) + "h ago";
    interval = seconds / 60;
    if (interval > 1) return Math.floor(interval) + "m ago";
    return "Just now";
}

function showMessage(msg, type) {
    const container = document.getElementById('message-container');
    const div = document.createElement('div');
    const bg = type === 'success' ? 'bg-green-100 border-green-200 text-green-700' : 'bg-red-100 border-red-200 text-red-700';
    div.className = `p-3 rounded-lg border text-sm font-medium ${bg} shadow-sm`;
    div.textContent = msg;
    container.innerHTML = '';
    container.appendChild(div);
    setTimeout(() => div.remove(), 3000);
}