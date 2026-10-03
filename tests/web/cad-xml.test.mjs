import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseXml, child, children, descendants, textOf } from '../../web/cad/xml.js';

test('parseXml builds a tree with attributes, text, CDATA and entities', () => {
  const doc = parseXml(`<?xml version="1.0"?>
    <!DOCTYPE x>
    <!-- comment -->
    <kml:root xmlns:kml="k" a="1 &amp; 2">
      <item id='x'>A &lt;b&gt; &#65;&#x42;</item>
      <item/>
      <note><![CDATA[<raw> & stuff]]></note>
    </kml:root>`);
  assert.equal(doc.name, 'root');
  assert.equal(doc.qname, 'kml:root');
  assert.equal(doc.attrs.a, '1 & 2');
  const items = children(doc, 'item');
  assert.equal(items.length, 2);
  assert.equal(items[0].attrs.id, 'x');
  assert.equal(textOf(items[0]), 'A <b> AB');
  assert.equal(textOf(child(doc, 'note')), '<raw> & stuff');
  assert.equal(descendants(doc, 'item').length, 2);
  assert.equal(child(doc, 'missing'), undefined);
});

test('parseXml rejects mismatched tags', () => {
  assert.throws(() => parseXml('<a><b></a>'));
});
