const fs = require('fs');
const MMDParser = require('mmd-parser');

const buf = fs.readFileSync('F:/BrainN/live2d-avatar/public/live2d/whale_girl/mmd/蓝色大肥鱼1.12.pmx');
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const parser = new MMDParser.Parser();
const model = parser.parsePmx(ab);

console.log('name:', model.metadata && model.metadata.name);
console.log('bones:', model.bones.length);
console.log('morphs:', model.morphs.length);
console.log('materials:', model.materials.length);
console.log('vertices:', model.vertices.length);
console.log('ik:', (model.ik || []).length);

const bones = model.bones.map((b) => b.name);
console.log('\n--- bone names ---');
console.log(bones.join(' | '));

const morphs = model.morphs.map((m) => m.name);
console.log('\n--- morph names ---');
console.log(morphs.join(' | '));

console.log('\n--- textures referenced ---');
console.log((model.metadata && model.metadata.texturesEncoding) || '');
console.log(model.materials.map((m) => String(m.diffuseTexture || '')).filter(Boolean).slice(0, 10).join('\n'));
