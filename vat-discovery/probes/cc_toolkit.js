// Browser-console toolkit used for the pilot runs against data.commoncrawl.org.
(() => {
  const w = new Worker(URL.createObjectURL(new Blob(
    ['onmessage=e=>{const [id,ms]=e.data; setTimeout(()=>postMessage(id),ms)}'], {type: 'text/javascript'})));
  const pend = new Map(); let sid = 0;
  w.onmessage = e => { const f = pend.get(e.data); pend.delete(e.data); f && f(); };
  const C = window.CC = {crawl: 'CC-MAIN-2026-43', throttled: 0, bytes: 0};
  C.base = `/cc-index/collections/${C.crawl}/indexes/`;
  C.sleep = ms => new Promise(res => { const id = ++sid; pend.set(id, res); w.postMessage([id, ms]); });  // not throttled in background tabs
  C.gunzip = async buf => new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  C.rfetch = async (url, a, b) => {
    for (let k = 0; k < 7; k++) {
      let r; try { r = await fetch(url, {headers: {Range: `bytes=${a}-${b}`}}); } catch (e) { C.throttled++; await C.sleep(20000 * (k + 1)); continue; }
      if (r.status === 206 || r.status === 200) { const buf = await r.arrayBuffer(); C.bytes += buf.byteLength; return buf; }
      if ([403, 429, 503].includes(r.status)) { C.throttled++; await C.sleep(20000 * (k + 1)); continue; }
      throw new Error('http ' + r.status);
    }
    throw new Error('gave up');
  };
  C.scheme = v => { if (!/^\d{9}$/.test(v) || v.startsWith('0000000')) return null; const cd = +v.slice(7); if (cd < 1 || cd > 97) return null;
    let s = cd; for (let i = 0; i < 7; i++) s += [8, 7, 6, 5, 4, 3, 2][i] * (+v[i]); return s % 97 == 0 ? '97' : ((s + 55) % 97 == 0 ? '9755' : null); };
  C.extract = html => {
    const out = {vat: {}, crn: {}, neg: false, title: '', text: ''};
    const add = (v, tag) => { if (C.scheme(v)) (out.vat[v] ||= new Set()).add(tag); };
    for (const m of html.matchAll(/"(?:vatID|taxID)"\s*:\s*"([^"]{5,30})"/gi)) add(m[1].replace(/\D/g, '').slice(0, 9), 'jsonld');
    let doc; try { doc = new DOMParser().parseFromString(html, 'text/html'); } catch (e) { return out; }
    out.title = (doc.title || '').slice(0, 80); doc.querySelectorAll('script,style,noscript,svg,template').forEach(n => n.remove());
    const T = out.text = (doc.body ? doc.body.textContent : '').replace(/[ \s]+/g, ' '); let m;
    const R1 = /\bV\.?A\.?T\b[^\d]{0,40}?(?:GB|UK)?\s*((?:\d[ .\-]?){8}\d)(?![ .\-]?\d)/gi; while ((m = R1.exec(T))) add(m[1].replace(/\D/g, ''), 'vatword');
    const R2 = /\bGB ?((?:\d[ .\-]?){8}\d)(?![ .\-]?\d)/g; while ((m = R2.exec(T))) add(m[1].replace(/\D/g, ''), 'gbprefix');
    const R3 = /\b(?:GB|XI) ?(\d{9}) ?000\b/g; while ((m = R3.exec(T))) add(m[1], 'eori');
    const R4 = /\b(?:compan(?:y|ies)|co\.?|registration|registered|reg\.?|crn)\b[^\d]{0,45}?(?<![A-Za-z0-9])((?:SC|NI|OC|SO|NC) ?\d{6}|\d{8}|\d{7}|\d{6})(?![\d])/gi;
    while ((m = R4.exec(T))) { if (/V\.?A\.?T/i.test(m[0])) continue; let c = m[1].replace(/\s/g, '').toUpperCase(); if (/^\d+$/.test(c)) c = c.padStart(8, '0'); out.crn[c] = (out.crn[c] || 0) + 1; }
    out.neg = /\bnot (?:currently )?(?:VAT[- ]registered|registered for VAT)\b/i.test(T);
    return out;
  };
  C.parseBlock = t => t.split('\n').filter(Boolean).map(l => { const i = l.indexOf(' '), j = l.indexOf(' ', i + 1); let o; try { o = JSON.parse(l.slice(j + 1)); } catch (e) { o = {}; } o.k = l.slice(0, i); return o; });
  C.fetchBlock = async b => C.parseBlock(await C.gunzip(await C.rfetch(C.base + b.f, b.o, b.o + b.len - 1)));
  C.fetchHtml = async r => { const t = await C.gunzip(await C.rfetch('/' + r.filename, +r.offset, +r.offset + +r.length - 1)); const i = t.indexOf('\r\n\r\n'); return t.slice(t.indexOf('\r\n\r\n', i + 4) + 4); };
  const LEGAL = /(terms|condition|privacy|legal|contact|about|imprint|company-info|disclaimer|cookie)/i;
  C.pickPages = caps => { caps = caps.filter(c => +c.length < 600000); if (!caps.length) return []; const home = caps.slice().sort((a, b) => a.k.length - b.k.length)[0];
    const legal = caps.filter(r => r !== home && LEGAL.test(r.url)).sort((a, b) => a.url.length - b.url.length)[0]; return legal ? [home, legal] : [home]; };
  // whole cluster.idx in memory -> one block fetch per host lookup, any TLD
  C.loadIndex = async () => { const t = await fetch(C.base + 'cluster.idx').then(r => r.text()); C.keys = []; C.blocks = [];
    for (const l of t.split('\n')) { const p = l.split('\t'); if (p.length >= 4) { const k = p[0].split(' ')[0]; C.keys.push(k); C.blocks.push({k, f: p[1], o: +p[2], len: +p[3]}); } } return C.keys.length; };
  C.blockIndex = surt => { const t = surt + ')/'; let lo = 0, hi = C.keys.length; while (lo < hi) { const m = (lo + hi) >> 1; if (C.keys[m] <= t) lo = m + 1; else hi = m; } return Math.max(0, lo - 1); };
  C.cache = new Map();
  C.capturesFor = async surt => { const i = C.blockIndex(surt); if (!C.cache.has(i)) { if (C.cache.size > 40) C.cache.delete(C.cache.keys().next().value); C.cache.set(i, await C.fetchBlock(C.blocks[i])); await C.sleep(250); }
    const pre = surt + ')'; return C.cache.get(i).filter(r => r.k.startsWith(pre) && r.status === '200' && /html/.test(r.mime || '')); };
  // name -> candidate hosts (port of vatdisc/guess.py + names.canonical)
  C.canonical = n => { let s = n.toUpperCase().replace(/[&+]/g, ' AND ').replace(/\b(T\/A|TRADING AS)\b.*$/, '').replace(/[.'’`]/g, '').replace(/[^A-Z0-9 ]/g, ' ');
    for (const [a, b] of [[/\bLIMITED LIABILITY PARTNERSHIP\b/g, 'LLP'], [/\bPUBLIC LIMITED COMPANY\b/g, 'PLC'], [/\bCOMMUNITY INTEREST COMPANY\b/g, 'CIC'], [/\bCYFYNGEDIG\b/g, 'LTD'], [/\bCYF\b/g, 'LTD'], [/\bLIMITED\b/g, 'LTD'], [/\bCOMPANY\b/g, 'CO'], [/\bCORPORATION\b/g, 'CORP'], [/\bINCORPORATED\b/g, 'INC']]) s = s.replace(a, b);
    return s.replace(/\s+/g, ' ').trim().replace(/^THE /, ''); };
  const DROP = new Set(['LTD', 'PLC', 'LLP', 'CIC', 'LP', 'UK', 'GB', 'HOLDINGS', 'GROUP', 'INTERNATIONAL']);
  C.labels = name => { const toks = C.canonical(name.replace(/\([^)]*\)/g, ' ')).split(' ').filter(t => t && !DROP.has(t)).map(t => t.toLowerCase());
    if (!toks.length || toks.join('').length < 4) return []; const out = [toks.join('')]; if (toks.length > 1) { out.push(toks.join('-')); const na = toks.filter(t => t !== 'and'); if (na.length !== toks.length && na.length) out.push(na.join('')); }
    return out.filter((l, i) => l.length > 3 && l.length <= 63 && out.indexOf(l) === i); };
  C.surtHosts = name => C.labels(name).flatMap(l => ['uk,co', 'com', 'uk'].map(t => `${t},${l}`));
})();
