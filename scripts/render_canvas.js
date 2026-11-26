// Rough Obsidian-like preview of a .canvas file -> PNG, for layout checks.
// Usage: NODE_PATH=$(npm root -g) node scripts/render_canvas.js vault/Maps/X.canvas /tmp/x.png   (needs Playwright)
const fs = require('fs'); const { chromium } = require('playwright');
const [,, inFile, outFile] = process.argv;
const c = JSON.parse(fs.readFileSync(inFile, 'utf8'));
const pal = {"1":"#e93147","2":"#ec7500","3":"#e0ac00","4":"#08b94e","5":"#00bfbc","6":"#7852ee"};
const col = v => v ? (pal[v] || v) : '#888';
const xs = c.nodes.flatMap(n => [n.x, n.x + n.width]), ys = c.nodes.flatMap(n => [n.y, n.y + n.height]);
const minX = Math.min(...xs) - 40, minY = Math.min(...ys) - 40, W = Math.max(...xs) - minX + 40, H = Math.max(...ys) - minY + 40;
const byId = Object.fromEntries(c.nodes.map(n => [n.id, n]));
const anchor = (n, s) => { const cx = n.x + n.width/2 - minX, cy = n.y + n.height/2 - minY;
  return s==='left'?[n.x-minX,cy]:s==='right'?[n.x+n.width-minX,cy]:s==='top'?[cx,n.y-minY]:s==='bottom'?[cx,n.y+n.height-minY]:[cx,cy]; };
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
const md = t => esc(t).split('\n').map(l => l.startsWith('## ')?`<h3>${l.slice(3)}</h3>`:l.startsWith('# ')?`<h2>${l.slice(2)}</h2>`:`<p>${l}</p>`).join('')
  .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\[(.+?)\]\((.+?)\)/g,'<u>$1</u>');
const lines = c.edges.map(e => { const [x1,y1]=anchor(byId[e.fromNode],e.fromSide), [x2,y2]=anchor(byId[e.toNode],e.toSide);
  const dx = Math.abs(x2-x1)/2; const path = (e.fromSide&&e.toSide)?`M${x1},${y1} C${x1+(e.fromSide==='right'?dx:-dx)},${y1} ${x2+(e.toSide==='left'?-dx:dx)},${y2} ${x2},${y2}`:`M${x1},${y1} L${x2},${y2}`;
  return `<path d="${path}" stroke="${col(e.color)}" stroke-width="3" fill="none" ${e.toEnd==='arrow'?'stroke-dasharray="8 6"':''}/>` + (e.label?`<text x="${(x1+x2)/2}" y="${(y1+y2)/2-8}" fill="#ccc" font-size="15" text-anchor="middle">${esc(e.label)}</text>`:''); }).join('');
const boxes = c.nodes.map(n => `<div class="n" style="left:${n.x-minX}px;top:${n.y-minY}px;width:${n.width}px;height:${n.height}px;border-color:${col(n.color)};background:${col(n.color)}22">${n.type==='text'?md(n.text):esc(n.file||n.url||'')}</div>`).join('');
const html = `<html><body style="margin:0;background:#1e1e1e;font-family:sans-serif"><div style="position:relative;width:${W}px;height:${H}px">
<svg width="${W}" height="${H}" style="position:absolute">${lines}</svg>${boxes}</div>
<style>.n{position:absolute;box-sizing:border-box;border:2px solid;border-radius:8px;padding:8px 14px;color:#ddd;font-size:15px;overflow:hidden}
h2{margin:2px 0;font-size:24px}h3{margin:2px 0;font-size:18px}p{margin:3px 0}u{color:#a88bfa}</style></body></html>`;
(async () => { const b = await chromium.launch(); const p = await b.newPage({viewport:{width:Math.ceil(W),height:Math.ceil(H)}});
  await p.setContent(html); await p.screenshot({path: outFile, fullPage: true}); await b.close(); console.log('rendered', Math.ceil(W)+'x'+Math.ceil(H)); })();
