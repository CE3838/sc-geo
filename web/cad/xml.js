// Small, dependency-free XML parser for KML and LandXML. Produces
// { name, qname, attrs, children, text } elements. Names are matched without
// their namespace prefix (`name`); `qname` keeps the prefix.

const ENTITIES = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

function decode(s) {
  if (!s.includes('&')) return s;
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, (m, ent) => {
    if (ent[0] === '#') {
      const code = ent[1] === 'x' ? parseInt(ent.slice(2), 16) : parseInt(ent.slice(1), 10);
      return String.fromCodePoint(code);
    }
    return ENTITIES[ent] ?? m;
  });
}

function element(qname, attrs) {
  const i = qname.indexOf(':');
  return { name: i < 0 ? qname : qname.slice(i + 1), qname, attrs, children: [], text: '' };
}

const ATTR = /([^\s=/>]+)\s*=\s*("([^"]*)"|'([^']*)')/g;

export function parseXml(src) {
  const stack = [];
  let root = null;
  let i = 0;
  const n = src.length;
  while (i < n) {
    const lt = src.indexOf('<', i);
    const textEnd = lt < 0 ? n : lt;
    if (textEnd > i && stack.length) stack[stack.length - 1].text += decode(src.slice(i, textEnd));
    if (lt < 0) break;
    if (src.startsWith('<!--', lt)) {
      const end = src.indexOf('-->', lt + 4);
      if (end < 0) throw new Error('Unterminated XML comment');
      i = end + 3;
    } else if (src.startsWith('<![CDATA[', lt)) {
      const end = src.indexOf(']]>', lt + 9);
      if (end < 0) throw new Error('Unterminated CDATA');
      if (stack.length) stack[stack.length - 1].text += src.slice(lt + 9, end);
      i = end + 3;
    } else if (src[lt + 1] === '?' || src[lt + 1] === '!') {
      const end = src.indexOf('>', lt);
      if (end < 0) throw new Error('Unterminated XML declaration');
      i = end + 1;
    } else if (src[lt + 1] === '/') {
      const end = src.indexOf('>', lt);
      const qname = src.slice(lt + 2, end).trim();
      const open = stack.pop();
      if (!open || open.qname !== qname) throw new Error(`Mismatched XML tag </${qname}>`);
      i = end + 1;
    } else {
      // Find the end of the tag, skipping '>' inside quoted attribute values.
      let j = lt + 1;
      let quote = null;
      for (; j < n; j++) {
        const c = src[j];
        if (quote) {
          if (c === quote) quote = null;
        } else if (c === '"' || c === "'") quote = c;
        else if (c === '>') break;
      }
      if (j >= n) throw new Error('Unterminated XML tag');
      let body = src.slice(lt + 1, j);
      const selfClosing = body.endsWith('/');
      if (selfClosing) body = body.slice(0, -1);
      const sp = body.search(/\s/);
      const qname = sp < 0 ? body : body.slice(0, sp);
      const attrs = {};
      if (sp >= 0) {
        for (const m of body.slice(sp).matchAll(ATTR)) attrs[m[1]] = decode(m[3] ?? m[4]);
      }
      const el = element(qname, attrs);
      if (stack.length) stack[stack.length - 1].children.push(el);
      else if (!root) root = el;
      if (!selfClosing) stack.push(el);
      i = j + 1;
    }
  }
  if (stack.length) throw new Error(`Unclosed XML tag <${stack[stack.length - 1].qname}>`);
  if (!root) throw new Error('No XML root element');
  return root;
}

export const child = (el, name) => el.children.find((c) => c.name === name);
export const children = (el, name) => el.children.filter((c) => c.name === name);
export const textOf = (el) => (el ? el.text.trim() : '');

export function descendants(el, name, out = []) {
  for (const c of el.children) {
    if (c.name === name) out.push(c);
    descendants(c, name, out);
  }
  return out;
}
