// Enhanced Quiz Timer with visual feedback
document.addEventListener('DOMContentLoaded', () => {
    if (typeof QUIZ_DURATION_SEC === 'undefined') return;

    const form = document.getElementById('quizForm');
    const timeTakenInput = document.getElementById('time_taken_sec');

    // Create floating timer
    const timerContainer = document.createElement('div');
    timerContainer.className = 'timer-container';
    timerContainer.innerHTML = `
    <div class="timer-display" id="timerDisplay">
      <i class="bi bi-clock-fill"></i>
      <span id="timerText">--:--</span>
    </div>
  `;
    document.body.appendChild(timerContainer);

    const timerDisplay = document.getElementById('timerDisplay');
    const timerText = document.getElementById('timerText');

    let remaining = QUIZ_DURATION_SEC;
    const total = QUIZ_DURATION_SEC;
    const warningThreshold = 60; // 1 minute warning
    const criticalThreshold = 30; // 30 seconds critical

    function formatTime(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = seconds % 60;
        return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
    }

    function tick() {
        timerText.textContent = formatTime(remaining);

        const used = total - remaining;
        if (timeTakenInput) timeTakenInput.value = used;

        // Visual warnings
        if (remaining <= criticalThreshold) {
            timerDisplay.classList.add('timer-warning');
            timerDisplay.style.background = 'linear-gradient(135deg, #dc2626 0%, #b91c1c 100%)';
        } else if (remaining <= warningThreshold) {
            timerDisplay.style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
        }

        if (remaining <= 0) {
            timerText.textContent = "Time's up!";
            // Auto-submit
            if (form) {
                form.submit();
            }
            return;
        }

        remaining -= 1;
        setTimeout(tick, 1000);
    }

    // Start timer
    tick();

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        timerContainer.remove();
    });
});
