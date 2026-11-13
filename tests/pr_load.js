// Loads the pattern-recognition block out of web/index.html so Node can test the code the phone really runs.
'use strict';
const fs = require('fs'), path = require('path');
module.exports = function load() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
  const a = html.indexOf('/*PR-BEGIN*/'), b = html.indexOf('/*PR-END*/');
  if (a < 0 || b < 0) throw new Error('PR block not found in web/index.html');
  return new Function(html.slice(a, b) + ';return {CycleTracker,EnvBuilder,CycleGate,VitalsPR};')();
};
