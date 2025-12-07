// API endpoint - configure this to your backend URL
// IMPORTANT: When deploying to GitHub Pages, replace with your actual backend URL
// For local development: 'http://localhost:5000/analyze'
// For production: Update this to your deployed backend URL (Render, Railway, etc.)
// Example: 'https://geoai-backend.onrender.com/analyze'

// API URL - automatically detects environment
const isProduction = window.location.hostname.includes('github.io') || 
                     window.location.hostname.includes('onrender.com') ||
                     (window.location.protocol === 'https:' && !window.location.hostname.includes('localhost'));

const API_URL = isProduction 
    ? 'https://crewai-test-tc2q.onrender.com/analyze'  // Production (Render)
    : 'http://192.168.1.84:5000/analyze';  // Local development

// Elements
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
const analyzeBtn = document.getElementById('analyzeBtn');
const clearBtn = document.getElementById('clearBtn');
const resultsSection = document.getElementById('resultsSection');
const resultsTableBody = document.getElementById('resultsTableBody');
const errorSection = document.getElementById('errorSection');
const errorMessage = document.getElementById('errorMessage');
const progressSection = document.getElementById('progressSection');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const progressLogs = document.getElementById('progressLogs');

let selectedFiles = [];

// Drag and drop handlers
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
});

function handleFiles(files) {
    const csvFiles = Array.from(files).filter(file => file.name.endsWith('.csv'));
    
    if (csvFiles.length === 0) {
        showError('Please select CSV files only.');
        return;
    }
    
    selectedFiles = [...selectedFiles, ...csvFiles];
    updateFileList();
    analyzeBtn.disabled = false;
    hideError();
}

function updateFileList() {
    fileList.innerHTML = '';
    selectedFiles.forEach((file, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        fileItem.innerHTML = `
            <span>${file.name}</span>
            <button onclick="removeFile(${index})" style="background: none; border: none; color: #d32f2f; cursor: pointer; font-size: 1.2em; margin-left: 10px;">×</button>
        `;
        fileList.appendChild(fileItem);
    });
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateFileList();
    if (selectedFiles.length === 0) {
        analyzeBtn.disabled = true;
    }
}

clearBtn.addEventListener('click', () => {
    selectedFiles = [];
    fileInput.value = '';
    updateFileList();
    analyzeBtn.disabled = true;
    resultsSection.style.display = 'none';
    hideError();
});

analyzeBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;
    
    // Show loading state
    analyzeBtn.disabled = true;
    analyzeBtn.querySelector('.btn-text').style.display = 'none';
    analyzeBtn.querySelector('.btn-loader').style.display = 'inline';
    
    hideError();
    resultsSection.style.display = 'none';
    showProgress();
    
    let progressInterval = null;
    
    try {
        const formData = new FormData();
        selectedFiles.forEach(file => {
            formData.append('files', file);
        });
        
        // Simulate progress while waiting
        progressInterval = simulateProgress(selectedFiles.length);
        
        const response = await fetch(API_URL, {
            method: 'POST',
            body: formData
        });
        
        if (progressInterval) {
            clearInterval(progressInterval);
        }
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Analysis failed');
        }
        
        updateProgress(100, 'Análise concluída!');
        addLog('Processamento finalizado com sucesso', 'success');
        
        const data = await response.json();
        
        if (data.status === 'success') {
            displayResults(data.results);
            if (data.token_stats) {
                updateTokenStats(data.token_stats);
            }
        } else {
            throw new Error('Analysis failed');
        }
        
        setTimeout(() => {
            hideProgress();
        }, 2000);
        
    } catch (error) {
        if (progressInterval) {
            clearInterval(progressInterval);
        }
        hideProgress();
        showError(`Error: ${error.message}`);
        addLog(`Erro: ${error.message}`, 'error');
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.querySelector('.btn-text').style.display = 'inline';
        analyzeBtn.querySelector('.btn-loader').style.display = 'none';
    }
});

function showProgress() {
    progressSection.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = 'Iniciando análise...';
    progressLogs.innerHTML = '';
    addLog('Preparando arquivos para análise...', 'processing');
}

function hideProgress() {
    progressSection.style.display = 'none';
}

function updateProgress(percent, text) {
    progressBar.style.width = percent + '%';
    if (text) {
        progressText.textContent = text;
    }
}

function addLog(message, type = 'processing') {
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry ${type}`;
    logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    progressLogs.appendChild(logEntry);
    progressLogs.scrollTop = progressLogs.scrollHeight;
}

function simulateProgress(fileCount) {
    let progress = 0;
    const steps = [
        { percent: 10, text: 'Enviando arquivos...', log: 'Enviando arquivos para o servidor...' },
        { percent: 20, text: 'Analisando estrutura...', log: 'Analisando estrutura dos arquivos CSV...' },
        { percent: 30, text: 'Identificando tipos...', log: 'Identificando tipos de arquivo (Collar, Survey, Assay, etc.)...' },
        { percent: 50, text: 'Identificando colunas...', log: 'Identificando colunas obrigatórias...' },
        { percent: 70, text: 'Validando dados...', log: 'Validando identificações...' },
        { percent: 85, text: 'Gerando resumo...', log: 'Gerando tabela consolidada...' },
        { percent: 95, text: 'Finalizando...', log: 'Preparando resultados...' }
    ];
    
    let stepIndex = 0;
    
    const interval = setInterval(() => {
        if (stepIndex < steps.length) {
            const step = steps[stepIndex];
            updateProgress(step.percent, step.text);
            addLog(step.log, 'processing');
            stepIndex++;
        } else if (progress < 95) {
            progress += 2;
            updateProgress(progress, 'Processando...');
        }
    }, 3000); // Update every 3 seconds
    
    return interval;
}

function displayResults(results) {
    resultsTableBody.innerHTML = '';
    
    if (!results || results.length === 0) {
        showError('No results to display');
        return;
    }
    
    results.forEach(row => {
        const tr = document.createElement('tr');
        
        const fileTypeTd = document.createElement('td');
        fileTypeTd.className = 'file-type';
        fileTypeTd.textContent = row.file_type;
        
        const fieldTd = document.createElement('td');
        fieldTd.className = 'field-name';
        fieldTd.textContent = row.field;
        
        const foundTd = document.createElement('td');
        const foundSpan = document.createElement('span');
        foundSpan.className = 'found-column';
        foundSpan.textContent = row.found;
        
        if (row.found === 'NOT FOUND') {
            foundSpan.classList.add('not-found');
        } else if (row.found === '(original column)') {
            foundSpan.classList.add('original');
        }
        
        foundTd.appendChild(foundSpan);
        
        const commentTd = document.createElement('td');
        commentTd.className = 'comment';
        commentTd.textContent = row.comment;
        
        tr.appendChild(fileTypeTd);
        tr.appendChild(fieldTd);
        tr.appendChild(foundTd);
        tr.appendChild(commentTd);
        
        resultsTableBody.appendChild(tr);
    });
    
    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

function showError(message) {
    errorMessage.textContent = message;
    errorSection.style.display = 'block';
}

function hideError() {
    errorSection.style.display = 'none';
}

// Make removeFile available globally
window.removeFile = removeFile;

// Token stats functions
async function loadTokenStats() {
    try {
        // Get base URL (remove /analyze if present)
        const baseUrl = API_URL.replace('/analyze', '');
        const statsUrl = `${baseUrl}/stats`;
        const response = await fetch(statsUrl);
        if (response.ok) {
            const stats = await response.json();
            updateTokenStats(stats);
        } else {
            console.warn('Stats endpoint not available:', response.status);
        }
    } catch (error) {
        // Silently fail - stats are optional
        console.warn('Could not load stats (this is OK if backend is not running):', error.message);
    }
}

function updateTokenStats(stats) {
    // Create or update stats display in header (top right corner)
    let statsDiv = document.getElementById('tokenStats');
    if (!statsDiv) {
        statsDiv = document.createElement('div');
        statsDiv.id = 'tokenStats';
        statsDiv.className = 'token-stats';
        const header = document.querySelector('header');
        header.appendChild(statsDiv);
    }
    
    const totalTokens = stats.total_tokens || (stats.total_input_tokens + stats.total_output_tokens);
    const cost = stats.total_cost || 0;
    const requests = stats.total_requests || 0;
    
    statsDiv.innerHTML = `
        <div class="stats-grid">
            <div class="stat-item">
                <span class="stat-label">Tokens:</span>
                <span class="stat-value">${totalTokens.toLocaleString()}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Cost:</span>
                <span class="stat-value">$${cost.toFixed(4)}</span>
            </div>
        </div>
    `;
}

// Load stats on page load
loadTokenStats();

