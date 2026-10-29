from pathlib import Path
root = Path(__file__).resolve().parent
source = root / 'src'
(root / 'index.html').write_text(
    (source / 'shell.html').read_text(encoding='utf-8')
    .replace('/*CSS*/', (source / 'style.css').read_text(encoding='utf-8'))
    .replace('/*JS*/', (source / 'app.js').read_text(encoding='utf-8')),
    encoding='utf-8'
)
print('Built index.html')
