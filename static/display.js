/**
 * display.js — Logique de l'écran géant
 * =======================================
 * Machine à états : BOOT → IDLE → CONNECTING → REVEAL → PLAYING → IDLE
 *
 * BOOT : écran de démarrage — un clic est requis pour déverrouiller l'autoplay
 *        navigateur (politique Chrome/Firefox sur les médias avec son).
 *        Une fois cliqué, le WS est établi et la Matrix démarre.
 *
 * Connexion WebSocket permanente vers /ws (établie après le clic BOOT).
 * Reconnexion automatique toutes les 3 secondes en cas de déconnexion.
 *
 * Messages WebSocket entrants :
 *   {type: "play",  user, category, video}  → démarre la séquence
 *   {type: "idle"}                           → retour à l'état IDLE
 *
 * Messages WebSocket sortants :
 *   {type: "video_ended"}  → envoyé quand la balise <video> se termine
 */

'use strict';

// ── Constantes ─────────────────────────────────────────────────────────────

const STATES = Object.freeze({
    BOOT:       'BOOT',       // Attente du clic initial (déverrouillage autoplay)
    IDLE:       'IDLE',       // Matrix + QR code
    CONNECTING: 'CONNECTING', // Glitch rouge
    REVEAL:     'REVEAL',     // Carte d'identité
    PLAYING:    'PLAYING',    // Vidéo plein écran
});

// Durées des transitions automatiques (ms)
const CONNECTING_DURATION = 2500;
const REVEAL_DURATION     = 4000;

// Animation Matrix
const MATRIX_FONT_SIZE = 16;
const MATRIX_CHARS     = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' +
                          '0123456789@#$%&*()[]{}|<>?+-=_アイウエオカキクケコ';


// ── Références DOM ──────────────────────────────────────────────────────────

const overlays = {
    boot:       document.getElementById('overlay-boot'),
    idle:       document.getElementById('overlay-idle'),
    connecting: document.getElementById('overlay-connecting'),
    reveal:     document.getElementById('overlay-reveal'),
    playing:    document.getElementById('overlay-playing'),
};

const domCardName      = document.getElementById('card-name');
const domCardCategory  = document.getElementById('card-category');
const domCreditName    = document.getElementById('credit-name');
const domConnectDots   = document.getElementById('connecting-dots');
const domMainVideo     = document.getElementById('main-video');
const domMatrixCanvas  = document.getElementById('matrix-canvas');

const ctx = domMatrixCanvas.getContext('2d');


// ── État courant ─────────────────────────────────────────────────────────────
// endedFallbackTimer : sécurité si le serveur ne répond pas après video_ended

let currentState        = STATES.IDLE;
let transitionTimer     = null;  // timer pour les transitions automatiques
let dotAnimTimer        = null;  // timer pour l'animation des points
let endedFallbackTimer  = null;  // sécurité : retour IDLE si le serveur ne répond pas
let allCategories       = [];    // chargé depuis /api/users au BOOT (slot machine)


// ── Machine à états ─────────────────────────────────────────────────────────

/**
 * Transition vers un nouvel état.
 * @param {string} newState  - Une valeur de STATES
 * @param {object} payload   - Données associées (user, category, video)
 */
function setState(newState, payload = {}) {
    // Annule tout timer de transition en cours
    clearTimeout(transitionTimer);
    clearInterval(dotAnimTimer);

    currentState = newState;

    // Masque toutes les couches
    Object.values(overlays).forEach(el => el.classList.remove('active'));

    switch (newState) {

        case STATES.BOOT:
            overlays.boot.classList.add('active');
            break;

        case STATES.IDLE:
            stopMatrix();
            overlays.idle.classList.add('active');
            startMatrix();
            break;

        case STATES.CONNECTING:
            stopMatrix();
            overlays.connecting.classList.add('active');
            animateDots();
            // Transition automatique vers REVEAL
            transitionTimer = setTimeout(() => setState(STATES.REVEAL, payload), CONNECTING_DURATION);
            break;

        case STATES.REVEAL: {
            overlays.reveal.classList.add('active');
            domCardName.textContent     = '';
            domCardCategory.textContent = '';
            typewriter(domCardName, payload.user || '', 90);
            // Slot machine après le nom, puis transition automatique vers PLAYING
            const nameDelay = (payload.user?.length || 0) * 90 + 300;
            setTimeout(() => {
                const cats = allCategories.length > 0 ? allCategories : [payload.category || ''];
                slotMachineCategory(domCardCategory, cats, payload.category || '', () => {
                    setState(STATES.PLAYING, payload);
                });
            }, nameDelay);
            break;
        }

        case STATES.PLAYING:
            overlays.playing.classList.add('active');
            domCreditName.textContent = payload.user || '';
            domMainVideo.src = '/static/videos/' + (payload.video || '');
            domMainVideo.play().catch(err => {
                // Autoplay bloqué (rare en kiosk) → log uniquement
                console.warn('[ZAPPING] Lecture automatique refusée :', err.message);
            });
            break;
    }
}


// ── Animation des points CONNECTING ────────────────────────────────────────

const DOT_FRAMES = [
    '▓░░░░░░░',
    '▓▓░░░░░░',
    '▓▓▓░░░░░',
    '▓▓▓▓░░░░',
    '▓▓▓▓▓░░░',
    '▓▓▓▓▓▓░░',
    '▓▓▓▓▓▓▓░',
    '▓▓▓▓▓▓▓▓',
];
let dotFrame = 0;

function animateDots() {
    dotAnimTimer = setInterval(() => {
        domConnectDots.textContent = DOT_FRAMES[dotFrame % DOT_FRAMES.length];
        dotFrame++;
    }, 250);
}


// ── Effet typewriter ────────────────────────────────────────────────────────

/**
 * Affiche `text` caractère par caractère dans `element`.
 * @param {HTMLElement} element
 * @param {string}      text
 * @param {number}      speed   Délai entre chaque caractère (ms)
 */
function typewriter(element, text, speed = 100) {
    element.textContent = '';
    let i = 0;
    const interval = setInterval(() => {
        if (i < text.length) {
            element.textContent += text[i++];
        } else {
            clearInterval(interval);
        }
    }, speed);
}


// ── Slot machine catégorie ──────────────────────────────────────────────────

/**
 * Animation "machine à sous" : défile les catégories aléatoirement,
 * ralentit progressivement, puis atterrit sur `target`.
 * @param {HTMLElement} element
 * @param {string[]}    categories  Toutes les catégories disponibles
 * @param {string}      target      La catégorie finale à afficher
 * @param {Function}    onComplete  Appelé quand l'animation est terminée
 */
function slotMachineCategory(element, categories, target, onComplete) {
    const DURATION   = 6800; // ms (~3s de plus qu'avant)
    const SPIN_COUNT = 42;   // items à défiler avant l'atterrissage

    // Séquence fixe : aléatoire (hors target) + target en dernier
    const pool = categories.length > 1 ? categories.filter(c => c !== target) : categories;
    const sequence = [];
    for (let i = 0; i < SPIN_COUNT; i++) {
        sequence.push(pool[Math.floor(Math.random() * pool.length)]);
    }
    sequence.push(target);

    let startTime  = null;
    let lastIdx    = -1;
    let flashTimer = null;

    function easeOutQuart(t) { return 1 - Math.pow(1 - t, 4); }
    function fmt(cat)        { return `[ ${cat.replace(/_/g, ' ').trim().toUpperCase()} ]`; }

    // 3 clignotements (6 demi-cycles), puis pause 2s avant de continuer
    function blinkAndPause() {
        const HALF_CYCLE = 250; // ms par demi-cycle (visible ou caché)
        let phase = 0;
        function tick() {
            if (phase >= 6) {
                element.style.opacity = '1';
                setTimeout(onComplete, 2000);
                return;
            }
            element.style.opacity = phase % 2 === 0 ? '0' : '1';
            phase++;
            setTimeout(tick, HALF_CYCLE);
        }
        tick();
    }

    function animate(ts) {
        if (!startTime) startTime = ts;
        const progress = Math.min((ts - startTime) / DURATION, 1);
        const eased    = easeOutQuart(progress);
        const idx      = Math.min(Math.round(eased * SPIN_COUNT), SPIN_COUNT);

        // Flou cinétique : fort au départ, s'efface avec la décélération
        const blur = Math.max(0, (1 - eased) * 6);
        element.style.filter = blur > 0.3 ? `blur(${blur.toFixed(1)}px)` : '';

        if (idx !== lastIdx) {
            lastIdx = idx;
            element.textContent = fmt(sequence[idx]);
            // Flash blanc → effet "clic" de roulette
            clearTimeout(flashTimer);
            element.style.color = '#ffffff';
            flashTimer = setTimeout(() => { element.style.color = ''; }, 55);
        }

        if (progress < 1) {
            requestAnimationFrame(animate);
        } else {
            clearTimeout(flashTimer);
            element.textContent  = fmt(target);
            element.style.color  = '';
            element.style.filter = '';
            blinkAndPause();
        }
    }

    requestAnimationFrame(animate);
}


// ── Animation Matrix (canvas) ───────────────────────────────────────────────

let matrixRunning = false;
let matrixRAF     = null;
let columns       = 0;
let drops         = [];

function initMatrixDimensions() {
    domMatrixCanvas.width  = window.innerWidth;
    domMatrixCanvas.height = window.innerHeight;
    columns = Math.floor(domMatrixCanvas.width / MATRIX_FONT_SIZE);
    drops   = new Array(columns).fill(1);
}

function drawMatrix() {
    if (!matrixRunning) return;

    // Fond semi-transparent pour l'effet de traînée progressive
    ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
    ctx.fillRect(0, 0, domMatrixCanvas.width, domMatrixCanvas.height);

    ctx.font = `${MATRIX_FONT_SIZE}px monospace`;

    for (let i = 0; i < columns; i++) {
        const char = MATRIX_CHARS[Math.floor(Math.random() * MATRIX_CHARS.length)];
        const x    = i * MATRIX_FONT_SIZE;
        const y    = drops[i] * MATRIX_FONT_SIZE;

        // Caractères de la traînée en vert
        ctx.fillStyle = '#00cc00';
        ctx.fillText(char, x, y);

        // Tête de colonne en blanc (effet caractère actif)
        ctx.fillStyle = '#aaffaa';
        ctx.fillText(char, x, y);

        // Réinitialise aléatoirement la colonne quand elle atteint le bas
        if (y > domMatrixCanvas.height && Math.random() > 0.975) {
            drops[i] = 0;
        }
        drops[i]++;
    }

    matrixRAF = requestAnimationFrame(drawMatrix);
}

function startMatrix() {
    if (matrixRunning) return;
    matrixRunning = true;
    initMatrixDimensions();
    drawMatrix();
}

function stopMatrix() {
    matrixRunning = false;
    if (matrixRAF) {
        cancelAnimationFrame(matrixRAF);
        matrixRAF = null;
    }
    // Efface le canvas (propre pour les overlays suivants)
    ctx.clearRect(0, 0, domMatrixCanvas.width, domMatrixCanvas.height);
}

// Recalcule les dimensions lors d'un redimensionnement de fenêtre
window.addEventListener('resize', () => {
    if (matrixRunning) initMatrixDimensions();
});


// ── Fin ou erreur de vidéo ───────────────────────────────────────────────────
// Fonction partagée par les événements 'ended' et 'error'.
// On NE revient PAS directement en IDLE : c'est le serveur qui décide
// si la file a encore des vidéos (next_video) ou si c'est terminé (idle).

function onVideoFinished() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'video_ended' }));
        // Sécurité : si le serveur ne répond pas dans 5s, on retourne quand même en IDLE
        endedFallbackTimer = setTimeout(() => setState(STATES.IDLE), 5000);
    } else {
        // Pas de connexion WS → retour IDLE immédiat
        setState(STATES.IDLE);
    }
}

domMainVideo.addEventListener('ended', onVideoFinished);
// 'error' couvre le cas où un fichier vidéo est manquant → la séquence continue
domMainVideo.addEventListener('error', onVideoFinished);


// ── WebSocket ────────────────────────────────────────────────────────────────

let ws               = null;
let wsReconnectTimer = null;

function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        console.log('[WS] Connecté au serveur.');
        clearTimeout(wsReconnectTimer);

        // Resynchronisation : si le serveur est déjà en PLAYING (reconnexion
        // après rechargement de page), on reprend l'état courant.
        fetch('/api/status')
            .then(r => r.json())
            .then(s => {
                if (s.status === 'PLAYING' && s.video) {
                    setState(STATES.PLAYING, {
                        user:     s.user,
                        category: s.category,
                        video:    s.video,
                    });
                }
            })
            .catch(() => { /* pas critique */ });
    };

    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            console.warn('[WS] Message non-JSON ignoré :', event.data);
            return;
        }

        if (data.type === 'play') {
            // 1ère vidéo de la file → animation complète CONNECTING → REVEAL → PLAYING
            setState(STATES.CONNECTING, data);
        } else if (data.type === 'next_video') {
            // Vidéo suivante dans la file → changement direct de src, pas d'animation
            clearTimeout(endedFallbackTimer);
            domMainVideo.src = '/static/videos/' + data.video;
            domMainVideo.play().catch(err =>
                console.warn('[ZAPPING] Lecture refusée :', err.message)
            );
        } else if (data.type === 'idle') {
            // File épuisée → retour en IDLE
            clearTimeout(endedFallbackTimer);
            setState(STATES.IDLE);
        }
    };

    ws.onclose = () => {
        console.warn('[WS] Déconnecté. Reconnexion dans 3s...');
        wsReconnectTimer = setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        ws.close(); // onclose prendra le relais pour la reconnexion
    };
}


// ── Polling de secours ───────────────────────────────────────────────────────
// Si le message WebSocket "play" est perdu (reconnexion, --reload, etc.),
// ce polling détecte le changement d'état côté serveur et démarre la séquence.
// Ne s'active qu'en état IDLE (pas pendant les animations ni en BOOT).

setInterval(async () => {
    if (currentState !== STATES.IDLE) return;
    try {
        const res = await fetch('/api/status');
        const s   = await res.json();
        if (s.status === 'PLAYING' && s.video) {
            console.log('[POLLING] État PLAYING détecté — démarrage séquence.');
            setState(STATES.CONNECTING, {
                user:     s.user,
                category: s.category,
                video:    s.video,
            });
        }
    } catch (_) { /* serveur non joignable, on ignore */ }
}, 2000);


// ── Démarrage ────────────────────────────────────────────────────────────────
// On démarre en BOOT : le clic déverrouille l'autoplay et lance le système.
// Le WS est volontairement connecté APRÈS le clic pour que le navigateur
// considère la connexion comme issue d'une interaction utilisateur.

overlays.boot.addEventListener('click', () => {
    setState(STATES.IDLE);
    connectWS();
    // Charge les catégories pour le slot machine REVEAL
    fetch('/api/categories')
        .then(r => r.json())
        .then(cats => { allCategories = cats; })
        .catch(() => { /* fallback : pool = [target], animation directe */ });
}, { once: true }); // once: true → handler supprimé automatiquement après le premier clic

setState(STATES.BOOT);
