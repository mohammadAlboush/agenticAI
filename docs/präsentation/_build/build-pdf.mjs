// Baut _print.html (12 Folien im Endzustand, 16:9 pro Seite) für Chrome --print-to-pdf.
// Jede Folie via <iframe src=... data-final="1"> — der data-final-Hook in jeder Folie
// setzt synchron den Endzustand (kein Timer, keine Animation).
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const DIR = process.argv[2] || 'C:/Users/moham/Desktop/Projekte/SEO - GEO/seogeo/ProjektPitch/docs/präsentation'
const N = 13

let pages = ''
for (let i = 1; i <= N; i++) {
  const nn = String(i).padStart(2, '0')
  pages += `  <div class="page"><iframe src="dd-folie-${nn}.html" data-final="1" scrolling="no"></iframe></div>\n`
}

const html = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>pitch-deck · print</title>
<style>
/* 1280×720 px = 13.333in × 7.5in = 338.67mm × 190.5mm (16:9) */
@page{ size: 338.667mm 190.5mm; margin: 0 }
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#fff}
.page{ width:1280px; height:720px; overflow:hidden; page-break-after:always; break-after:page; position:relative }
.page:last-child{ page-break-after:auto; break-after:auto }
iframe{ width:1280px; height:720px; border:0; display:block }
@media print{ .page{ box-shadow:none } }
</style>
</head>
<body>
${pages}</body>
</html>
`

writeFileSync(join(DIR, '_print.html'), html, 'utf8')
console.log('_print.html geschrieben ·', N, 'Seiten')
