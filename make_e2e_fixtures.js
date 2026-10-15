#!/usr/bin/env node
/**
 * make_e2e_fixtures.js —— 生成端到端测试用的 NCM 样本
 *
 * 三条独立性保证：
 *   1. AES 用 Node 内置 crypto（OpenSSL），不是我们自己的实现；
 *   2. 音频密钥流用「照规范逐偏移计算、不打表」的参考实现，不复用 ncm_core 的查表版；
 *   3. 每首歌的元数据都不同，这样输出文件名唯一，能精确回溯到来源。
 *
 * 产出 e2e-fixtures/*.ncm 和 e2e-fixtures/expected.json
 */
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'e2e-fixtures');
fs.mkdirSync(OUT, { recursive: true });

const NCM_MAGIC = Buffer.from([0x43, 0x54, 0x45, 0x4e, 0x46, 0x44, 0x41, 0x4d]);
const CORE_KEY = Buffer.from('687a4852416d736f356b496e62617857', 'hex');
const META_KEY = Buffer.from('2331346c6a6b5f215c5d2630553c2728', 'hex');

// ── 独立参考实现：标准 RC4 的 KSA + NCM 改造过的、只依赖绝对偏移的 PRGA ──
function refKsa(key) {
  const S = new Uint8Array(256);
  for (let i = 0; i < 256; i++) S[i] = i;
  let j = 0;
  for (let i = 0; i < 256; i++) {
    j = (j + S[i] + key[i % key.length]) % 256;
    const t = S[i]; S[i] = S[j]; S[j] = t;
  }
  return S;
}
function refXor(buf, key) {
  const S = refKsa(key);
  const out = Buffer.from(buf);
  for (let off = 0; off < out.length; off++) {
    const j = (off + 1) % 256;
    const a = S[j];
    const b = S[(a + j) % 256];
    out[off] ^= S[(a + b) % 256];
  }
  return out;
}

function buildNcm(audio, meta, cover, opts = {}) {
  const framePad = opts.framePad || 0;
  const hideCoverLen = !!opts.hideCoverLen;

  const keyData = crypto.randomBytes(16);
  const keyPlain = Buffer.concat([Buffer.from('neteasecloudmusic'), keyData]);
  const c = crypto.createCipheriv('aes-128-ecb', CORE_KEY, null);
  const keyBlob = Buffer.concat([c.update(keyPlain), c.final()]);
  for (let i = 0; i < keyBlob.length; i++) keyBlob[i] ^= 0x64;

  const metaPlain = 'music:' + JSON.stringify(meta);
  const mc = crypto.createCipheriv('aes-128-ecb', META_KEY, null);
  const metaCipher = Buffer.concat([mc.update(Buffer.from(metaPlain, 'utf8')), mc.final()]);
  const metaBlob = Buffer.from("163 key(Don't modify):" + metaCipher.toString('base64'), 'latin1');
  for (let i = 0; i < metaBlob.length; i++) metaBlob[i] ^= 0x63;

  const coverBuf = cover || Buffer.alloc(0);
  const declaredCoverLen = hideCoverLen ? 0 : coverBuf.length;
  const coverFrameLen = coverBuf.length + framePad;

  const head = Buffer.alloc(10);
  NCM_MAGIC.copy(head, 0);

  const keyLenBuf = Buffer.alloc(4); keyLenBuf.writeUInt32LE(keyBlob.length, 0);
  const metaLenBuf = Buffer.alloc(4); metaLenBuf.writeUInt32LE(metaBlob.length, 0);
  const tail = Buffer.alloc(13);
  tail.writeUInt32LE(0, 0);                    // crc32
  tail.writeUInt8(0, 4);                       // image version
  tail.writeUInt32LE(coverFrameLen, 5);
  tail.writeUInt32LE(declaredCoverLen, 9);

  return Buffer.concat([
    head, keyLenBuf, keyBlob, metaLenBuf, metaBlob, tail,
    coverBuf, Buffer.alloc(framePad), refXor(audio, keyData),
  ]);
}

// ── 素材 ──
function fakeMp3(seed, size) {
  const body = Buffer.alloc(size);
  let x = seed >>> 0;
  for (let i = 0; i < size; i++) { x = (x * 1103515245 + 12345) >>> 0; body[i] = x >>> 16 & 0xff; }
  return Buffer.concat([Buffer.from([0xff, 0xfb, 0x90, 0x64]), body]);
}
function fakeJpeg(seed, size) {
  const body = Buffer.alloc(size);
  let x = seed >>> 0;
  for (let i = 0; i < size; i++) { x = (x * 1103515245 + 12345) >>> 0; body[i] = x >>> 16 & 0xff; }
  return Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), body, Buffer.from([0xff, 0xd9])]);
}
function fakePng(seed, size) {
  const body = Buffer.alloc(size);
  let x = seed >>> 0;
  for (let i = 0; i < size; i++) { x = (x * 1103515245 + 12345) >>> 0; body[i] = x >>> 16 & 0xff; }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), body]);
}

const spec = [];

function emit(fileName, audio, meta, cover, opts) {
  const buf = buildNcm(audio, meta, cover, opts);
  fs.writeFileSync(path.join(OUT, fileName), buf);
  const rec = {
    ncm: fileName,
    ext: audio.slice(0, 4).toString('latin1') === 'fLaC' ? 'flac' : 'mp3',
    audioSha256: crypto.createHash('sha256').update(audio).digest('hex'),
    audioBytes: audio.length,
    meta: {
      title: meta.musicName,
      artist: meta.artist.map((a) => a[0]).join(' / '),
      album: meta.album,
      track: meta.track || 0,
    },
    cover: cover ? {
      sha256: crypto.createHash('sha256').update(cover).digest('hex'),
      mime: cover[0] === 0xff ? 'image/jpeg' : 'image/png',
      bytes: cover.length,
    } : null,
  };
  spec.push(rec);
  console.log(`  ${fileName.padEnd(26)} ${rec.ext.padEnd(5)} ${String(audio.length).padStart(8)} 字节` +
              `  封面=${rec.cover ? rec.cover.mime : '无'}`);
  return rec;
}

console.log('生成端到端测试样本:');

// 甲：MP3 + JPEG 封面
emit('jia-mp3.ncm',
  fakeMp3(1, 400000),
  { musicName: '甲曲', artist: [['歌手甲', 1], ['歌手乙', 2]], album: '甲专辑',
    bitrate: 320000, duration: 215000, track: 1, format: 'mp3' },
  fakeJpeg(11, 30000), {});

// 乙：真 FLAC + PNG 封面（payload.flac 由 make_flac_payload.py 生成，结构合法）
const flacPath = path.join(OUT, 'payload.flac');
if (!fs.existsSync(flacPath)) {
  console.error('缺少 e2e-fixtures/payload.flac，请先运行 python make_flac_payload.py');
  process.exit(2);
}
const flacPayload = fs.readFileSync(flacPath);
emit('yi-flac.ncm', flacPayload,
  { musicName: '乙曲', artist: [['某无损歌手', 7]], album: '乙专辑',
    bitrate: 1411200, duration: 10000, track: 2, format: 'flac' },
  fakePng(22, 12000), { framePad: 4096 });

// 丙：MP3，无封面，cover_len=0 + padding（最容易踩坑的布局）
emit('bing-mp3.ncm',
  fakeMp3(3, 350000),
  { musicName: '丙曲', artist: [['丙歌手', 3]], album: '丙专辑',
    bitrate: 128000, duration: 180000, track: 3, format: 'mp3' },
  null, { hideCoverLen: true, framePad: 2048 });

// 丁：甲曲的完全副本，用于验证批内去重
fs.copyFileSync(path.join(OUT, 'jia-mp3.ncm'), path.join(OUT, 'ding-dup.ncm'));
console.log('  ding-dup.ncm               （甲曲的副本，用于验证去重）');

fs.writeFileSync(path.join(OUT, 'expected.json'),
  JSON.stringify({ fixtures: spec, note: 'ding-dup.ncm 是 jia-mp3.ncm 的副本' }, null, 1));
console.log(`\n共 ${spec.length} 个唯一样本 + 1 个副本 -> ${OUT}/expected.json`);
