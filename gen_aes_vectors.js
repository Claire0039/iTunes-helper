#!/usr/bin/env node
/**
 * gen_aes_vectors.js —— 用 Node 内置 crypto 生成 AES-128-ECB 测试向量
 *
 * 目的是给 ncm_core.py 里手写的纯 Python AES 解密实现找一个独立裁判：
 * 用 Node（OpenSSL）加密，用 Python 解密，逐字节比对。
 */
'use strict';
const crypto = require('crypto');
const fs = require('fs');

const vectors = [];

// 1) FIPS-197 标准向量（单分组，无填充）
vectors.push({
  name: 'FIPS-197 C.1',
  key: '000102030405060708090a0b0c0d0e0f',
  ciphertext: '69c4e0d86a7b0430d8cdb78070b4c55a',
  plaintext: '00112233445566778899aabbccddeeff',
  padded: false,
});

// 2) 随机向量：用 Node 加密（PKCS#7），Python 侧解密后应与原文一致
for (let i = 0; i < 40; i++) {
  const key = crypto.randomBytes(16);
  const len = 1 + Math.floor(Math.random() * 200);
  const plain = crypto.randomBytes(len);
  const c = crypto.createCipheriv('aes-128-ecb', key, null);
  c.setAutoPadding(true);
  const ct = Buffer.concat([c.update(plain), c.final()]);
  vectors.push({
    name: `random-${i}`,
    key: key.toString('hex'),
    ciphertext: ct.toString('hex'),
    plaintext: plain.toString('hex'),
    padded: true,
  });
}

// 3) 故意等于 16 字节倍数的明文：验证 PKCS#7 会补一整块
for (let i = 0; i < 10; i++) {
  const key = crypto.randomBytes(16);
  const plain = crypto.randomBytes(16 * (1 + Math.floor(Math.random() * 4)));
  const c = crypto.createCipheriv('aes-128-ecb', key, null);
  const ct = Buffer.concat([c.update(plain), c.final()]);
  vectors.push({
    name: `block-aligned-${i}`,
    key: key.toString('hex'),
    ciphertext: ct.toString('hex'),
    plaintext: plain.toString('hex'),
    padded: true,
  });
}

fs.writeFileSync('aes_vectors.json', JSON.stringify(vectors, null, 1));
console.log(`已生成 ${vectors.length} 条 AES 测试向量 -> aes_vectors.json`);
