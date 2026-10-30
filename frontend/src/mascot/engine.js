/** Relay's original SVG mascot. No framework, images, network or animation library. */
export const SHAPES = {
  blob: {
    body: 'M47 8C71 6 87 22 88 44C90 59 83 71 76 77L80 86Q82 92 76 89L63 83C40 91 13 81 7 59C0 34 16 11 47 8Z',
    face: 'M46 25C64 21 77 31 79 46C82 63 68 74 47 74C27 74 15 64 16 48C16 33 29 26 46 25Z',
  },
  wedge: {
    body: 'M38 12Q48 0 58 13L88 66Q97 84 76 87L21 87Q0 86 8 66Z',
    face: 'M41 30Q48 20 55 31L73 63Q78 73 66 75L30 75Q18 74 24 63Z',
  },
  gem: {
    body: 'M36 10Q48 0 60 10L87 35Q99 48 87 61L60 86Q48 97 36 86L9 61Q-3 48 9 35Z',
    face: 'M39 27Q48 19 57 27L74 42Q81 49 74 57L57 72Q48 79 39 72L22 57Q15 49 22 42Z',
  },
};

// [Chinese, English, Indonesian], independent from React's i18n system.
const state = (group, labels, eyes, motion, badge = '') => ({ group, labels, eyes, motion, badge });
// Each eye is [width scale, height scale, rotation degrees]. No pupils, highlights, mouth or nose.
export const EMOTIONS = {
  boot: state('lifecycle', ['开机', 'Starting up', 'Memulai'], [[1, 1, 0], [1, 1, 0]], 'boot'),
  wake: state('lifecycle', ['唤醒', 'Waking up', 'Bangun'], [[1, 1.15, -5], [1, 1.15, 5]], 'wake'),
  idle: state('lifecycle', ['待机', 'Ready', 'Siap'], [[1, 1, 0], [1, 1, 0]], 'breathe'),
  sleep: state('lifecycle', ['休眠', 'Sleeping', 'Tidur'], [[1.45, .16, 0], [1.45, .16, 0]], 'sleep'),
  loading: state('lifecycle', ['加载', 'Loading', 'Memuat'], [[1, .8, 0], [1, .8, 0]], 'loading', 'dots'),
  shutdown: state('lifecycle', ['关闭', 'Shutting down', 'Menutup'], [[1.3, .14, 0], [1.3, .14, 0]], 'shutdown'),
  happy: state('emotion', ['开心', 'Happy', 'Senang'], [[1.25, .42, -14], [1.25, .42, 14]], 'bounce'),
  surprised: state('emotion', ['惊讶', 'Surprised', 'Terkejut'], [[1.15, 1.35, 0], [1.15, 1.35, 0]], 'surprised'),
  thinking: state('emotion', ['思考', 'Thinking', 'Berpikir'], [[1, .8, -12], [1, 1.05, -12]], 'thinking'),
  questioning: state('emotion', ['疑问', 'Curious', 'Penasaran'], [[1, 1.2, 0], [1.2, .5, 8]], 'tilt', 'question'),
  sad: state('emotion', ['难过', 'Sad', 'Sedih'], [[1.1, .65, -22], [1.1, .65, 22]], 'sad'),
  focused: state('emotion', ['专注', 'Focused', 'Fokus'], [[1.15, .58, 12], [1.15, .58, -12]], 'focus'),
  proud: state('emotion', ['得意', 'Proud', 'Bangga'], [[1.3, .3, -12], [1.3, .3, 12]], 'proud'),
  listening: state('agent', ['倾听中', 'Listening', 'Mendengarkan'], [[1, 1.05, -4], [1, 1.05, 4]], 'listen'),
  searching: state('agent', ['检索中', 'Searching', 'Mencari'], [[1, .9, 0], [1, .9, 0]], 'search', 'search'),
  working: state('agent', ['执行中', 'Working', 'Mengerjakan'], [[1, .7, 8], [1, .7, -8]], 'work', 'dots'),
  speaking: state('agent', ['回复中', 'Responding', 'Menjawab'], [[1, 1, 0], [1, 1, 0]], 'speak'),
  waiting_approval: state('agent', ['等待审批', 'Awaiting approval', 'Menunggu persetujuan'], [[1, 1, -6], [1, 1, 6]], 'wait', 'pause'),
  waiting: state('agent', ['等待回复', 'Awaiting a reply', 'Menunggu balasan'], [[1, .8, 0], [1, .8, 0]], 'wait', 'dots'),
  error: state('agent', ['遇到错误', 'Error', 'Terjadi kesalahan'], [[1.15, .6, -20], [1.15, .6, 20]], 'error', 'error'),
  completed: state('agent', ['任务完成', 'Task completed', 'Tugas selesai'], [[1.3, .35, -14], [1.3, .35, 14]], 'complete', 'check'),
  offline: state('agent', ['离线', 'Offline', 'Luring'], [[1.2, .2, 0], [1.2, .2, 0]], 'still', 'offline'),
};

export function resolveEmotion(value) {
  return typeof value === 'string' && Object.hasOwn(EMOTIONS, value) ? value : 'idle';
}
export function resolveShape(value) {
  return typeof value === 'string' && Object.hasOwn(SHAPES, value) ? value : 'blob';
}
const badges = {
  dots: '<circle cx="74" cy="19" r="1.4"/><circle cx="79" cy="19" r="1.4"/><circle cx="84" cy="19" r="1.4"/>',
  search: '<circle cx="77" cy="17" r="3.8" fill="none" stroke="currentColor" stroke-width="2"/><path d="m80 20 4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  pause: '<rect x="75" y="14" width="2.5" height="10" rx="1"/><rect x="81" y="14" width="2.5" height="10" rx="1"/>',
  error: '<path d="m75 15 8 8m0-8-8 8" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
  check: '<path d="m74 19 3.5 3.5 7-8" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
  question: '<path d="M76 16a3 3 0 0 1 6 0c0 2-3 2-3 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="79" cy="24" r="1"/>',
  offline: '<path d="m74 24 10-10M75 16h5v5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
};
const eyeTransform = ([x, y, angle]) => `rotate(${angle}deg) scale(${x}, ${y})`;
const themeCSS = `svg[data-relay-mascot]{display:block;overflow:visible}svg[data-relay-mascot] [data-part=body]{transform-origin:48px 48px}svg[data-relay-mascot] [data-eye]{transform-origin:0 0}svg[data-relay-mascot] .shell{fill:var(--relay-shell,#c96442)}svg[data-relay-mascot] .face{fill:var(--relay-face,#fff3df)}svg[data-relay-mascot] .eye{fill:var(--relay-eye,#25231f)}svg[data-relay-mascot] .blush{fill:var(--relay-blush,#e7b5a0);opacity:.7}svg[data-relay-mascot] [data-part=badge]{color:var(--relay-badge-ink,#25231f);fill:currentColor}svg[data-relay-mascot] .badge-bg{fill:var(--relay-badge,#faf9f5);stroke:var(--relay-shell,#c96442);stroke-width:1.5}@media(prefers-color-scheme:dark){svg[data-relay-mascot] .shell{fill:var(--relay-shell,#df896b)}svg[data-relay-mascot] .face{fill:var(--relay-face,#f2dfc6)}svg[data-relay-mascot] .blush{fill:var(--relay-blush,#d79c89)}svg[data-relay-mascot] .badge-bg{fill:var(--relay-badge,#35312c)}svg[data-relay-mascot] [data-part=badge]{color:var(--relay-badge-ink,#f5f4ef)}}`;

/** Static source for app icons and standalone consumers. Inputs are allowlisted. */
export function renderRelaySvg({ shape = 'blob', emotionId = 'idle', standalone = true, monochrome = false } = {}) {
  const geometry = SHAPES[resolveShape(shape)];
  const [left, right, eyeY, cheekX, cheekY] = resolveShape(shape) === 'wedge' ? [39, 57, 55, 32, 68]
    : resolveShape(shape) === 'gem' ? [37, 59, 49, 30, 60] : [35, 61, 47, 25, 59];
  const emotion = EMOTIONS[resolveEmotion(emotionId)];
  const shell = monochrome ? 'fill="none" stroke="#000" stroke-width="6"' : 'class="shell"';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" fill="none" aria-hidden="true" focusable="false" data-relay-mascot="${resolveEmotion(emotionId)}" data-shape="${resolveShape(shape)}">
    ${standalone ? `<style>${themeCSS}</style>` : ''}
    <g data-part="body"><path data-part="shell" d="${geometry.body}" ${shell}/>
      ${monochrome ? '' : `<path data-part="face" class="face" d="${geometry.face}"/><g data-part="cheeks" class="blush"><ellipse cx="${cheekX}" cy="${cheekY}" rx="5.5" ry="3"/><ellipse cx="${96 - cheekX}" cy="${cheekY}" rx="5.5" ry="3"/></g>`}
      <g data-part="gaze"><g transform="translate(${left} ${eyeY})"><g data-eye="left" style="transform:${eyeTransform(emotion.eyes[0])}"><rect class="eye" x="-4" y="-9" width="8" height="18" rx="4" ${monochrome ? 'fill="#000"' : ''}/></g></g>
      <g transform="translate(${right} ${eyeY})"><g data-eye="right" style="transform:${eyeTransform(emotion.eyes[1])}"><rect class="eye" x="-4" y="-9" width="8" height="18" rx="4" ${monochrome ? 'fill="#000"' : ''}/></g></g></g>
    </g><g data-part="badge" ${emotion.badge ? '' : 'display="none"'}><circle class="badge-bg" cx="79" cy="19" r="11"/>${badges[emotion.badge] || ''}</g>
  </svg>`;
}

/** Native Web Animations, stopped off screen/in hidden tabs/reduced-motion mode. */
export function createRelayMascot(host, options = {}) {
  let emotionId = resolveEmotion(options.emotionId);
  let shape = resolveShape(options.shape);
  let animated = options.animated !== false;
  let visible = true;
  let destroyed = false;
  let animations = [];
  let svg, body, gaze, eyes;
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const cancel = () => { animations.forEach(animation => animation.cancel()); animations = []; };
  const animate = (node, frames, duration, iterations = Infinity) => {
    if (!node?.animate) return;
    animations.push(node.animate(frames, { duration, iterations, easing: 'ease-in-out', fill: 'both' }));
  };
  function play() {
    cancel();
    if (destroyed || !animated || !visible || document.hidden || motion.matches) return;
    const config = EMOTIONS[emotionId];
    const base = 'translateY(0px) rotate(0deg) scale(1)';
    const bodyFrames = (middle, duration, repeat = Infinity) => animate(body, [{ transform: base }, { transform: middle }, { transform: base }], duration, repeat);
    switch (config.motion) {
      case 'boot': animate(body, [{ opacity: .3, transform: 'scale(.6)' }, { opacity: 1, transform: 'scale(1.06)', offset: .75 }, { opacity: 1, transform: 'scale(1)' }], 900, 1); break;
      case 'wake': bodyFrames('translateY(-3px) scale(1.04)', 1100, 1); break;
      case 'sleep': bodyFrames('translateY(1px) scale(1.018,.98)', 4800); break;
      case 'shutdown': animate(body, [{ opacity: 1, transform: 'scale(1)' }, { opacity: .4, transform: 'scale(.94)' }], 900, 1); break;
      case 'bounce': bodyFrames('translateY(-4px) rotate(-3deg)', 1800); break;
      case 'surprised': bodyFrames('translateY(-3px) scale(1.06)', 700, 1); break;
      case 'thinking': bodyFrames('rotate(-5deg)', 3200); animate(gaze, [{ transform: 'translate(0,0)' }, { transform: 'translate(-2px,-3px)' }, { transform: 'translate(0,0)' }], 3200); break;
      case 'tilt': bodyFrames('rotate(8deg)', 2600); break;
      case 'sad': bodyFrames('translateY(2px) rotate(-3deg)', 4000); break;
      case 'focus': animate(gaze, [{ transform: 'translateY(0)' }, { transform: 'translateY(2px)' }, { transform: 'translateY(0)' }], 3400); break;
      case 'proud': bodyFrames('translateY(-2px) rotate(5deg)', 2400); break;
      case 'listen': bodyFrames('rotate(-3deg)', 2600); break;
      case 'search': animate(gaze, [{ transform: 'translateX(-5px)' }, { transform: 'translateX(5px)' }, { transform: 'translateX(-5px)' }], 2200); break;
      case 'loading': bodyFrames('rotate(4deg) scale(.98,1.02)', 1400); break;
      case 'work': bodyFrames('translateY(-2px) rotate(-2deg)', 1600); break;
      case 'speak': bodyFrames('scale(1.025, .985)', 1100); break;
      case 'wait': bodyFrames('translateY(-1px)', 4200); break;
      case 'error': animate(body, [0, -4, 4, -3, 3, 0].map(x => ({ transform: `translateX(${x}px)` })), 550, 1); break;
      case 'complete': bodyFrames('translateY(-5px) rotate(-5deg) scale(1.04)', 850, 2); break;
      case 'still': break;
      default: bodyFrames('translateY(-1px) scale(1.012)', 4500);
    }
    if (!['sleep', 'shutdown', 'offline'].includes(emotionId)) eyes.forEach((eye, index) => {
      const resting = eyeTransform(config.eyes[index]);
      animate(eye, [{ transform: resting, offset: 0 }, { transform: resting, offset: .87 },
        { transform: `${resting} scaleY(.12)`, offset: .9 }, { transform: resting, offset: .93 }, { transform: resting, offset: 1 }], 5200);
    });
  }
  function render() {
    cancel();
    // Only constant SVG markup and allowlisted IDs enter this string.
    host.innerHTML = renderRelaySvg({ emotionId, shape });
    svg = host.firstElementChild;
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '100%');
    body = svg.querySelector('[data-part="body"]');
    gaze = svg.querySelector('[data-part="gaze"]');
    eyes = [...svg.querySelectorAll('[data-eye]')];
    host.dataset.emotion = emotionId;
    host.dataset.shape = shape;
    play();
  }
  render();
  const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
    const next = entries[0].isIntersecting;
    if (visible !== next) { visible = next; play(); }
  }) : null;
  observer?.observe(host);
  motion.addEventListener('change', play);
  document.addEventListener('visibilitychange', play);
  return {
    setEmotion(value) {
      if (destroyed) return;
      const next = resolveEmotion(value);
      if (next === emotionId) return;
      emotionId = next; render();
    },
    setShape(value) {
      if (destroyed) return;
      const next = resolveShape(value);
      if (next === shape) return;
      shape = next; render();
    },
    setAnimated(value) { if (!destroyed && animated !== Boolean(value)) { animated = Boolean(value); play(); } },
    handleAIMessage(message) {
      let value;
      try { value = typeof message === 'string' ? JSON.parse(message) : message; } catch { value = null; }
      this.setEmotion(value && typeof value === 'object' ? value.emotionId : null);
      return emotionId;
    },
    replay() { play(); },
    destroy() {
      if (destroyed) return;
      destroyed = true; cancel(); observer?.disconnect();
      motion.removeEventListener('change', play); document.removeEventListener('visibilitychange', play);
      host.replaceChildren();
    },
  };
}
