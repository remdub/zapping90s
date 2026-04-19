/**
 * mobile.js — Logique du contrôleur smartphone
 * ==============================================
 * Flux :
 *   INTRO  → saisie du prénom
 *   QUIZ   → 3 questions (une par pool, tirées depuis /api/quiz)
 *   LOADING→ barre ASCII pendant l'appel à /api/quiz/result
 *   CHOICE → affichage de la catégorie + 3 vidéos au choix
 *   WAITING→ attente WS {type: "idle"} pour revenir à INTRO
 *   ERROR  → message d'erreur + retry
 *
 * WebSocket :
 *   Connexion permanente. "idle" remet l'interface en INTRO.
 *   Reconnexion automatique toutes les 3 secondes.
 */

'use strict';

// ── Constantes ───────────────────────────────────────────────────────────────

const LOADING_DURATION_MS = 1500;
const PROGRESS_BLOCKS     = 20;
const ANSWER_LETTERS      = ['A', 'B', 'C', 'D'];


// ── État de la session ───────────────────────────────────────────────────────

let userName      = '';          // prénom saisi à l'INTRO
let questions     = [];          // 3 questions chargées depuis /api/quiz
let answers       = [];          // catégories choisies (ex: ["cinema__", "geek__", "sport__"])
let quizStep      = 0;           // index de la question courante (0, 1, 2)
let quizResult    = null;        // { category, label, videos } retourné par /api/quiz/result


// ── Gestion des écrans ───────────────────────────────────────────────────────

const screens = {
    intro:   document.getElementById('screen-intro'),
    quiz:    document.getElementById('screen-quiz'),
    loading: document.getElementById('screen-loading'),
    choice:  document.getElementById('screen-choice'),
    waiting: document.getElementById('screen-waiting'),
    error:   document.getElementById('screen-error'),
};

function showScreen(name) {
    Object.entries(screens).forEach(([key, el]) => {
        el.classList.toggle('active', key === name);
    });
}

function showError(message) {
    document.getElementById('error-msg').textContent = message;
    showScreen('error');
}


// ── Chargement des questions ─────────────────────────────────────────────────

async function loadQuestions() {
    try {
        const res = await fetch('/api/quiz');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        questions = data.questions;
    } catch (err) {
        console.error('[ZAPPING] Impossible de charger le quiz :', err);
        showError('Impossible de charger le quiz.\nVérifiez la connexion réseau.');
    }
}


// ── Barre de progression ASCII ───────────────────────────────────────────────

function animateProgressBar(durationMs, onComplete) {
    const barEl     = document.getElementById('progress-bar');
    const percentEl = document.getElementById('progress-percent');
    const interval  = durationMs / PROGRESS_BLOCKS;
    let   progress  = 0;

    barEl.textContent     = '[' + '░'.repeat(PROGRESS_BLOCKS) + ']';
    percentEl.textContent = '0%';

    const timer = setInterval(() => {
        progress++;
        barEl.textContent     = `[${'█'.repeat(progress)}${'░'.repeat(PROGRESS_BLOCKS - progress)}]`;
        percentEl.textContent = `${Math.round((progress / PROGRESS_BLOCKS) * 100)}%`;

        if (progress >= PROGRESS_BLOCKS) {
            clearInterval(timer);
            if (typeof onComplete === 'function') onComplete();
        }
    }, interval);
}


// ── Quiz : affichage d'une question ─────────────────────────────────────────

function showQuestion(index) {
    const q = questions[index];

    // Barre de progression textuelle ex: [█░░]
    const filled = '█'.repeat(index + 1);
    const empty  = '░'.repeat(3 - index - 1);
    document.getElementById('quiz-step').textContent        = index + 1;
    document.getElementById('quiz-progress-bar').textContent = `[${filled}${empty}]`;

    document.getElementById('quiz-question').textContent = q.question;

    const container = document.getElementById('quiz-answers');
    container.innerHTML = '';

    q.answers.forEach((answer, i) => {
        const btn = document.createElement('button');
        btn.className = 'answer-btn';
        btn.innerHTML =
            `<span class="answer-letter">[${ANSWER_LETTERS[i]}]</span>${answer.text}`;

        btn.addEventListener('click', () => onAnswerSelected(answer.category), { once: true });
        container.appendChild(btn);
    });
}

function onAnswerSelected(category) {
    answers.push(category);
    quizStep++;

    if (quizStep < 3) {
        showQuestion(quizStep);
    } else {
        // Quiz terminé → calcul du profil
        showScreen('loading');
        animateProgressBar(LOADING_DURATION_MS, submitQuiz);
    }
}


// ── Soumission du quiz → résultat + choix vidéos ─────────────────────────────

async function submitQuiz() {
    try {
        const res = await fetch('/api/quiz/result', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name: userName, answers }),
        });

        if (res.status === 409) {
            showError(
                'Une vidéo est déjà en cours de lecture.\n' +
                'Veuillez patienter la fin de la séquence.'
            );
            return;
        }

        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showError(body.detail || `Erreur serveur (${res.status}). Réessayez.`);
            return;
        }

        quizResult = await res.json();
        showChoiceScreen();

    } catch (err) {
        console.error('[ZAPPING] Erreur réseau :', err);
        showError('Impossible de contacter le serveur.\nVérifiez la connexion réseau.');
    }
}


// ── Écran CHOICE : affichage des 3 vidéos ───────────────────────────────────

function showChoiceScreen() {
    document.getElementById('choice-category').textContent =
        `[ ${quizResult.label} ]`;

    const container = document.getElementById('choice-videos');
    container.innerHTML = '';

    quizResult.videos.forEach((video, i) => {
        const btn = document.createElement('button');
        btn.className = 'video-btn';
        btn.innerHTML = `<span class="video-num">[${i + 1}]</span>${video.title}`;
        btn.addEventListener('click', () => onVideoSelected(video.filename), { once: true });
        container.appendChild(btn);
    });

    showScreen('choice');
}


// ── Sélection d'une vidéo → lancement sur l'écran géant ─────────────────────

async function onVideoSelected(filename) {
    // Désactive tous les boutons pour éviter un double-clic
    document.querySelectorAll('.video-btn').forEach(b => { b.disabled = true; });

    try {
        const res = await fetch('/api/play', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                name:     userName,
                category: quizResult.category,
                video:    filename,
            }),
        });

        if (res.status === 409) {
            showError(
                'Une vidéo est déjà en cours de lecture.\n' +
                'Veuillez patienter la fin de la séquence.'
            );
            return;
        }

        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showError(body.detail || `Erreur serveur (${res.status}). Réessayez.`);
            return;
        }

        showScreen('waiting');

    } catch (err) {
        console.error('[ZAPPING] Erreur réseau :', err);
        showError('Impossible de contacter le serveur.\nVérifiez la connexion réseau.');
    }
}


// ── Réinitialisation pour une nouvelle session ───────────────────────────────

function resetSession() {
    userName   = '';
    answers    = [];
    quizStep   = 0;
    quizResult = null;
    document.getElementById('name-input').value = '';
    // Recharge les questions pour varier les variantes
    loadQuestions();
    showScreen('intro');
}


// ── Boutons ──────────────────────────────────────────────────────────────────

document.getElementById('start-btn').addEventListener('click', () => {
    const name = document.getElementById('name-input').value.trim();
    if (!name) {
        document.getElementById('name-input').focus();
        return;
    }
    if (questions.length === 0) {
        showError('Les questions du quiz ne sont pas encore chargées.\nRechargez la page.');
        return;
    }
    userName = name;
    answers  = [];
    quizStep = 0;
    showScreen('quiz');
    showQuestion(0);
});

// Validation via "Entrée" sur le champ prénom
document.getElementById('name-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('start-btn').click();
});

document.getElementById('retry-btn').addEventListener('click', resetSession);


// ── WebSocket ────────────────────────────────────────────────────────────────

let ws               = null;
let wsReconnectTimer = null;

function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        clearTimeout(wsReconnectTimer);
        console.log('[WS] Connecté au serveur.');
    };

    ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data); } catch { return; }

        // La séquence est terminée → retour à l'INTRO
        if (data.type === 'idle') {
            if (screens.waiting.classList.contains('active')) {
                resetSession();
            }
        }
    };

    ws.onclose = () => {
        console.warn('[WS] Déconnecté. Reconnexion dans 3s...');
        wsReconnectTimer = setTimeout(connectWS, 3000);
    };

    ws.onerror = () => { ws.close(); };
}


// ── Démarrage ────────────────────────────────────────────────────────────────

loadQuestions();
connectWS();
