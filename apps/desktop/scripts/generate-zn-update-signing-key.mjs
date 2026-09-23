#!/usr/bin/env node
import { generateKeyPairSync } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'

const outputDir = path.resolve(process.argv[2] || '.zn-update-signing')
await fs.mkdir(outputDir, { recursive: true, mode: 0o700 })

const { privateKey, publicKey } = generateKeyPairSync('ed25519')
const privatePem = privateKey.export({ format: 'pem', type: 'pkcs8' })
const publicDer = publicKey.export({ format: 'der', type: 'spki' })
const privatePath = path.join(outputDir, 'zn-update-private-key.pem')
const publicPath = path.join(outputDir, 'zn-update-public-key.txt')

for (const candidate of [privatePath, publicPath]) {
  try {
    await fs.access(candidate)
    throw new Error(`refusing to overwrite existing update signing material: ${candidate}`)
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
}

await fs.writeFile(privatePath, privatePem, { mode: 0o600 })
await fs.writeFile(publicPath, `${publicDer.toString('base64')}\n`, { mode: 0o600 })

console.log(`private key: ${privatePath}`)
console.log(`public key:  ${publicPath}`)
console.log('Store the private PEM only in GitHub secret ZN_UPDATE_SIGNING_PRIVATE_KEY.')
console.log('Store the public base64 value in repository variable ZN_UPDATE_SIGNING_PUBLIC_KEYS.')
