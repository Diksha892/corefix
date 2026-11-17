/* Corefix 2.0 interaction layer. Guided helper is intentionally local/rule-based. */
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Scroll progress and progressive reveal for content added on every page.
  const progress = $('#scrollProgress');
  const updateProgress = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (progress) progress.style.width = `${max > 0 ? (window.scrollY / max) * 100 : 0}%`;
  };
  updateProgress();
  window.addEventListener('scroll', updateProgress, { passive: true });
  const revealObserver = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('visible'); revealObserver.unobserve(entry.target); }
  }), { threshold: .08 });
  $$('.reveal').forEach(el => revealObserver.observe(el));

  // Cursor ambience (desktop only).
  const glow = $('.pointer-glow');
  if (glow && matchMedia('(pointer:fine)').matches && !reduceMotion) {
    window.addEventListener('pointermove', e => {
      glow.style.left = `${e.clientX}px`; glow.style.top = `${e.clientY}px`; glow.style.opacity = '.9';
    }, { passive: true });
    document.addEventListener('pointerleave', () => { glow.style.opacity = '0'; });
  }

  // Gentle 3D tilt for selected showcase surfaces.
  if (!reduceMotion && matchMedia('(pointer:fine)').matches) {
    $$('[data-tilt]').forEach(el => {
      el.addEventListener('pointermove', e => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - .5;
        const y = (e.clientY - r.top) / r.height - .5;
        el.style.transform = `perspective(1100px) rotateX(${(-y * 3).toFixed(2)}deg) rotateY(${(x * 4).toFixed(2)}deg) translateY(-2px)`;
      });
      el.addEventListener('pointerleave', () => { el.style.transform = ''; });
    });
  }

  // Homepage perspective switcher.
  const previewCopy = $('#previewTabCopy');
  const previewTexts = {
    people: 'A straightforward place to report what needs attention, add the right details and check progress without chasing updates.',
    ops: 'A structured view of incoming requests, priority signals, facility hotspots and status history — helping teams focus on the next best action.'
  };
  $$('[data-preview-tab]').forEach(btn => btn.addEventListener('click', () => {
    $$('[data-preview-tab]').forEach(b => b.classList.toggle('active', b === btn));
    if (previewCopy) { previewCopy.style.opacity = '0'; setTimeout(() => { previewCopy.textContent = previewTexts[btn.dataset.previewTab]; previewCopy.style.opacity = '1'; }, 130); }
  }));

  // Quick command palette.
  const overlay = $('#commandOverlay'), commandInput = $('#commandInput');
  const routes = { report: '/report', track: '/track', heatmap: '/heatmap', dashboard: '/admin' };
  const openCommands = () => { if (!overlay) return; overlay.hidden = false; setTimeout(() => commandInput?.focus(), 30); };
  const closeCommands = () => { if (overlay) overlay.hidden = true; };
  $$('[data-command-open]').forEach(b => b.addEventListener('click', openCommands));
  $$('[data-command]').forEach(b => b.addEventListener('click', () => { const path = routes[b.dataset.command]; if (path) location.href = path; }));
  overlay?.addEventListener('click', e => { if (e.target === overlay) closeCommands(); });
  commandInput?.addEventListener('input', () => {
    const q = commandInput.value.toLowerCase();
    $$('.command-box>button').forEach(b => b.hidden = !b.textContent.toLowerCase().includes(q));
  });
  commandInput?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { const first = $$('.command-box>button').find(b => !b.hidden); first?.click(); }
  });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openCommands(); }
    if (e.key === 'Escape') { closeCommands(); closeCopilot(); }
  });

  // Corefix Copilot: interactive guided help grounded in the current app's real routes and rules.
  const launcher = $('#copilotLauncher'), panel = $('#copilotPanel'), conversation = $('#copilotConversation');
  const question = $('#copilotQuestion');
  const openCopilot = () => { if (!panel) return; panel.hidden = false; launcher?.setAttribute('aria-expanded', 'true'); setTimeout(() => question?.focus(), 80); };
  function closeCopilot() { if (panel) panel.hidden = true; launcher?.setAttribute('aria-expanded', 'false'); }
  launcher?.addEventListener('click', () => panel.hidden ? openCopilot() : closeCopilot());
  $('#copilotClose')?.addEventListener('click', closeCopilot);

  function addMessage(text, who = 'bot', html = false) {
    if (!conversation) return;
    const item = document.createElement('div'); item.className = `copilot-message ${who}`;
    const mark = document.createElement('span'); mark.className = 'message-mark'; mark.textContent = who === 'bot' ? '✳' : '•';
    const bubble = document.createElement('div');
    if (html) bubble.innerHTML = text; else { const p = document.createElement('p'); p.textContent = text; bubble.append(p); }
    item.append(mark, bubble); conversation.append(item); conversation.scrollTop = conversation.scrollHeight;
  }
  function respond(raw) {
    const q = raw.toLowerCase();
    if (/^(hi|hello|hey)\b/.test(q)) return 'Hey! I can help you use Corefix. Try asking about reporting, ticket tracking, priority levels or facility locations.';
    if (/(report|raise|submit|new issue|complaint)/.test(q)) return 'To report an issue, open the guided form. Add who is reporting, a clear title and description, the exact facility location, then choose severity. Corefix suggests a category and priority from the details you provide.';
    if (/(track|ticket|status|where.*request|complaint id)/.test(q)) {
      const ticket = raw.toUpperCase().match(/CF-\d{4,}/);
      return ticket ? `I can open the tracker for ${ticket[0]}. Use the ticket search on the tracking page to view its latest status and activity history.` : 'Open Track a request and enter the ticket reference from your confirmation. Ticket references look like CF-0007. You can also paste the ID into the tracker search.';
    }
    if (/(priority|severity|urgent|critical|score|safety)/.test(q)) return 'Priority is calculated from three signals: category points, severity points and a safety-risk signal. Electrical issues carry more category points, higher severity adds more points, and a detected safety risk adds 30 points. The score maps to Low, Medium, High or Critical.';
    if (/(location|map|heatmap|hotspot|where)/.test(q)) return 'The facility heatmap groups locations into Academic, Residential and Common zones. You can switch between open and all reports, filter by category, then select a location tile to inspect its issue summary.';
    if (/(admin|operations|dashboard|team)/.test(q)) return 'The Operations area is for authorised administrators. It provides issue filters, status and priority summaries, and issue-level updates. Choose Admin portal in the top navigation to sign in.';
    if (/(resolved|under review|in progress|submitted)/.test(q)) return 'A request moves through four statuses: Submitted → Under Review → In Progress → Resolved. The tracking page shows the current stage and the recorded activity timeline.';
    if (/(help|what can you do|options)/.test(q)) return 'I can guide you through reporting an issue, tracking a ticket, understanding the priority score, exploring the heatmap or finding the operations dashboard.';
    return 'I can help with Corefix workflows: reporting a new issue, tracking a CF ticket, understanding priority scoring, exploring the facility heatmap or using the admin dashboard. Which one are you working on?';
  }
  function handleCopilot(text) {
    const clean = text.trim(); if (!clean) return;
    addMessage(clean, 'user');
    const answer = respond(clean);
    setTimeout(() => addMessage(answer, 'bot'), 220);
  }
  $('#copilotForm')?.addEventListener('submit', e => { e.preventDefault(); handleCopilot(question.value); question.value = ''; });
  $$('[data-copilot]').forEach(btn => btn.addEventListener('click', () => {
    const key = btn.dataset.copilot;
    const actions = {
      report: ['I want to report an issue', 'Open the guided report form to describe the issue, choose a location and review the live triage suggestion.'],
      track: ['I want to track my request', 'Open the tracker and enter your CF ticket ID. The page shows the current status, milestone journey and activity history.'],
      priority: ['How does priority work?', respond('How is priority calculated?')],
      map: ['Show me the facility map', 'The heatmap groups Academic, Residential and Common locations. You can filter by status or category and select a tile for details.']
    };
    const [q, a] = actions[key]; addMessage(q, 'user'); setTimeout(() => addMessage(a, 'bot'), 180);
    if (key === 'report') setTimeout(() => { const a = document.createElement('a'); a.className = 'copilot-inline-link'; a.href = '/report'; a.textContent = 'Open report form ↗'; conversation.append(a); }, 230);
    if (key === 'track') setTimeout(() => { const a = document.createElement('a'); a.className = 'copilot-inline-link'; a.href = '/track'; a.textContent = 'Open request tracker ↗'; conversation.append(a); }, 230);
    if (key === 'map') setTimeout(() => { const a = document.createElement('a'); a.className = 'copilot-inline-link'; a.href = '/heatmap'; a.textContent = 'Explore facility heatmap ↗'; conversation.append(a); }, 230);
    conversation.scrollTop = conversation.scrollHeight;
  }));

  // Keyboard shortcut hint and accessible focus behaviour.
  document.addEventListener('click', e => {
    if (panel && !panel.hidden && !panel.contains(e.target) && !launcher?.contains(e.target)) {
      // Keep panel open while interacting elsewhere; user closes it explicitly.
    }
  });
})();
