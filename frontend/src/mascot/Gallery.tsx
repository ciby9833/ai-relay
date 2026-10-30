import { useState } from 'react';
import { useLocale } from '../useLocale';
import LanguageSelect from '../components/LanguageSelect';
import RelayMascot from '../components/RelayMascot';
import { EMOTIONS, type EmotionId, type MascotShape } from './engine.js';
import './gallery.css';

export default function MascotGallery() {
  const { locale } = useLocale();
  const index = locale === 'zh' ? 0 : locale === 'id' ? 2 : 1;
  const copy = (zh: string, en: string, id: string) => [zh, en, id][index];
  const [emotion, setEmotion] = useState<EmotionId>('idle');
  const [shape, setShape] = useState<MascotShape>('blob');
  const [theme, setTheme] = useState('auto');
  const [playing, setPlaying] = useState(true);
  const [replay, setReplay] = useState(0);
  const groups = [
    ['lifecycle', copy('生命周期', 'Lifecycle', 'Siklus hidup')],
    ['emotion', copy('情绪反应', 'Expressions', 'Ekspresi')],
    ['agent', copy('代理工作状态', 'Agent activity', 'Aktivitas asisten')],
  ];
  const label = EMOTIONS[emotion].labels[index];
  return <main className="mascot-gallery" data-mascot-theme={theme}>
    <header className="mascot-gallery-head">
      <a href="/" className="mascot-brand"><RelayMascot size={36} /><span>Relay</span></a>
      <LanguageSelect />
    </header>
    <div className="mascot-intro"><p className="mascot-kicker">RELAY · 01</p>
      <h1>{copy('一个有表情的小助理', 'A little assistant with personality', 'Asisten kecil dengan kepribadian')}</h1>
      <p>{copy('选一个状态，看它如何回应。', 'Choose a state and see how it responds.', 'Pilih keadaan dan lihat responsnya.')}</p>
    </div>
    <div className="mascot-gallery-layout">
      <section className="mascot-stage" aria-label={copy('动画预览', 'Animation preview', 'Pratinjau animasi')}>
        <div className="mascot-stage-avatar"><RelayMascot key={replay} size={192} shape={shape} emotionId={emotion} animated={playing} label={`Relay · ${label}`} /></div>
        <h2 aria-live="polite">{label}</h2><code>{emotion}</code>
        <div className="mascot-playback">
          <button className="btn secondary" onClick={() => setPlaying(!playing)}>{playing ? copy('暂停', 'Pause', 'Jeda') : copy('播放', 'Play', 'Putar')}</button>
          <button className="btn secondary" onClick={() => { setPlaying(true); setReplay(n => n + 1); }}>{copy('重播', 'Replay', 'Ulangi')}</button>
        </div>
        <label className="field"><span>{copy('身体形态', 'Body shape', 'Bentuk tubuh')}</span><select value={shape} onChange={e => setShape(e.target.value as MascotShape)}>
          <option value="blob">{copy('圆胖', 'Blob', 'Bulat')}</option><option value="wedge">{copy('三角', 'Wedge', 'Segitiga')}</option><option value="gem">{copy('菱形', 'Gem', 'Permata')}</option>
        </select></label>
        <label className="field"><span>{copy('外观', 'Appearance', 'Tampilan')}</span><select value={theme} onChange={e => setTheme(e.target.value)}>
          <option value="auto">{copy('跟随系统', 'System', 'Ikuti sistem')}</option><option value="light">{copy('浅色', 'Light', 'Terang')}</option><option value="dark">{copy('深色', 'Dark', 'Gelap')}</option>
        </select></label>
        <p className="mascot-motion-note">{copy('开启系统“减少动态效果”时，保留静态表情。', 'Reduced motion keeps the expression still.', 'Kurangi gerakan menampilkan ekspresi statis.')}</p>
        <div className="mascot-sizes" aria-label={copy('小尺寸预览', 'Small-size previews', 'Pratinjau ukuran kecil')}>
          {[16, 24, 32, 48].map(size => <div key={size}><RelayMascot size={size} shape={shape} emotionId={emotion} /><small>{size}px</small></div>)}
        </div>
      </section>
      <div className="mascot-expression-groups">{groups.map(([group, title]) => <section key={group}>
        <h2>{title}</h2><div className="mascot-expression-grid">
          {(Object.keys(EMOTIONS) as EmotionId[]).filter(id => EMOTIONS[id].group === group).map(id => <button key={id}
            className="mascot-expression" aria-pressed={emotion === id} onClick={() => { setEmotion(id); setReplay(n => n + 1); }}>
            <RelayMascot size={52} shape={shape} emotionId={id} />
            <span>{EMOTIONS[id].labels[index]}</span><code>{id}</code>
          </button>)}
        </div>
      </section>)}</div>
    </div>
  </main>;
}
