// Chart.js initialization with error handling
document.addEventListener('DOMContentLoaded', function () {
    const apiUrl = window.PERFORMANCE_API_URL;

    if (!apiUrl) {
        console.error('Performance API URL not set');
        return;
    }

    // Fetch chart data
    fetch(apiUrl)
        .then(response => {
            if (!response.ok) throw new Error('API error');
            return response.json();
        })
        .then(data => {
            console.log('Chart data:', data);
            renderTopicChart(data.topics || []);
            renderProgressChart(data.history || []);
        })
        .catch(error => {
            console.error('Chart error:', error);
            showChartPlaceholder();
        });
});

function renderTopicChart(topics) {
    const canvas = document.getElementById('topicChart');
    if (!canvas || topics.length === 0) {
        showPlaceholder('topicChart', 'Complete quizzes to see topic performance');
        return;
    }

    const ctx = canvas.getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: topics.map(t => t.topic),
            datasets: [{
                label: 'Accuracy (%)',
                data: topics.map(t => Math.round(t.accuracy * 100)),
                backgroundColor: 'rgba(102, 126, 234, 0.8)',
                borderColor: 'rgba(102, 126, 234, 1)',
                borderWidth: 2,
                borderRadius: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { color: '#9ca3af' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' }
                },
                x: {
                    ticks: { color: '#9ca3af' },
                    grid: { display: false }
                }
            }
        }
    });
}

function renderProgressChart(history) {
    const canvas = document.getElementById('progressChart');
    if (!canvas || history.length === 0) {
        showPlaceholder('progressChart', 'Complete quizzes to track progress');
        return;
    }

    const ctx = canvas.getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: history.map(h => new Date(h.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })),
            datasets: [{
                label: 'Accuracy (%)',
                data: history.map(h => Math.round(h.accuracy * 100)),
                borderColor: 'rgba(56, 239, 125, 1)',
                backgroundColor: 'rgba(56, 239, 125, 0.1)',
                borderWidth: 3,
                tension: 0.4,
                fill: true,
                pointBackgroundColor: 'rgba(56, 239, 125, 1)',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { color: '#9ca3af' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' }
                },
                x: {
                    ticks: { color: '#9ca3af' },
                    grid: { display: false }
                }
            }
        }
    });
}

function showPlaceholder(canvasId, message) {
    const canvas = document.getElementById(canvasId);
    if (canvas) {
        canvas.parentNode.innerHTML = `<div class="text-center text-muted py-5"><i class="bi bi-graph-up opacity-25" style="font-size: 3rem;"></i><p class="mt-3">${message}</p></div>`;
    }
}

function showChartPlaceholder() {
    showPlaceholder('topicChart', 'Unable to load chart data');
    showPlaceholder('progressChart', 'Unable to load chart data');
}
