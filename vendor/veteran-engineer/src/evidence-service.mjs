import fs from 'node:fs/promises';
import path from 'node:path';
import { isStateCommitAuditOutcomeUnknown } from './state-backend-durability-contract.mjs';
import { nowIso, randomId, sha256, stableStringify } from './util.mjs';

const MAX_ATTACHMENTS = 128;
const MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024;
const MAX_ATTACHMENT_TOTAL_BYTES = 64 * 1024 * 1024;
const MAX_QUERY_IMAGES = 4;
const MAX_QUERY_IMAGE_BYTES = 4 * 1024 * 1024;
const MAX_QUERY_IMAGE_TOTAL_BYTES = 8 * 1024 * 1024;
const REMOTE_SCREENSHOT_EXTENSION = '.png';
const REMOTE_SCREENSHOT_MIME_TYPE = 'image/png';
const PNG_SIGNATURE = Buffer.from('89504e470d0a1a0a', 'hex');

function attachmentExtension(name) {
  const ext = path.extname(String(name || '')).toLowerCase();
  return /^\.[a-z0-9]{1,12}$/.test(ext) ? ext : '.bin';
}

function evidenceImageError(code, message, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function buildEvidenceRecord({
  id,
  projectId,
  missionId = null,
  taskId = null,
  type,
  summary,
  sourceIdentity = null,
  runtimeIdentity = null,
  artifactPointer = null,
  artifactHash = null,
  attachments = [],
  metadata = {}
}) {
  return {
    id,
    projectId,
    missionId,
    taskId,
    type,
    summary: typeof summary === 'string' ? summary.slice(0, 4000) : stableStringify(summary).slice(0, 4000),
    sourceIdentity,
    runtimeIdentity,
    artifactPointer,
    artifactHash,
    attachments,
    metadata,
    createdAt: nowIso()
  };
}

function attachEvidenceRecord(state, record) {
  state.evidence[record.id] = record;
  if (record.taskId && record.missionId) {
    const task = state.tasks[`${record.missionId}:${record.taskId}`];
    if (task && !task.evidenceIds.includes(record.id)) task.evidenceIds.push(record.id);
  }
}

async function cleanupUncommittedFiles(paths) {
  await Promise.allSettled(paths.map((full) => fs.rm(full, { force: true })));
}

export class EvidenceService {
  constructor({ store }) {
    this.store = store;
  }

  prepareMetadataRecord({ projectId, missionId = null, taskId = null, type, summary, sourceIdentity = null, runtimeIdentity = null, metadata = {} }) {
    return buildEvidenceRecord({
      id: randomId('evidence'),
      projectId,
      missionId,
      taskId,
      type,
      summary,
      sourceIdentity,
      runtimeIdentity,
      artifactPointer: null,
      artifactHash: null,
      attachments: [],
      metadata
    });
  }

  attachPreparedRecord(state, record) {
    if (!record || typeof record !== 'object' || !record.id || record.artifactPointer !== null || record.artifactHash !== null || !Array.isArray(record.attachments) || record.attachments.length !== 0) {
      throw new TypeError('prepared evidence record must be metadata-only');
    }
    attachEvidenceRecord(state, record);
    return record;
  }

  async record({ projectId, missionId = null, taskId = null, type, summary, sourceIdentity = null, runtimeIdentity = null, artifact = null, attachments = [], metadata = {} }) {
    const id = randomId('evidence');
    if (!Array.isArray(attachments)) throw new TypeError('evidence attachments must be an array');
    if (attachments.length > MAX_ATTACHMENTS) throw new RangeError(`evidence attachments may contain at most ${MAX_ATTACHMENTS} files`);

    const artifactContent = artifact !== null && artifact !== undefined
      ? (typeof artifact === 'string' ? artifact : `${JSON.stringify(artifact, null, 2)}\n`)
      : null;
    const artifactFilename = artifactContent !== null ? `${id}.txt` : null;
    const artifactPointer = artifactFilename ? `artifacts/${artifactFilename}` : null;
    const artifactHash = artifactContent !== null ? sha256(artifactContent) : null;

    let attachmentTotalBytes = 0;
    const normalizedAttachments = attachments.map((item, index) => {
      if (!item || typeof item !== 'object' || !item.name || (typeof item.content !== 'string' && !Buffer.isBuffer(item.content) && !(item.content instanceof Uint8Array))) {
        throw new TypeError('evidence attachment must provide name and string/binary content');
      }
      const content = typeof item.content === 'string' ? Buffer.from(item.content) : Buffer.from(item.content);
      if (content.length > MAX_ATTACHMENT_BYTES) throw new RangeError(`evidence attachment exceeds ${MAX_ATTACHMENT_BYTES} bytes`);
      attachmentTotalBytes += content.length;
      if (attachmentTotalBytes > MAX_ATTACHMENT_TOTAL_BYTES) throw new RangeError(`evidence attachments exceed ${MAX_ATTACHMENT_TOTAL_BYTES} total bytes`);
      const filename = `${id}-${String(index + 1).padStart(3, '0')}${attachmentExtension(item.name)}`;
      return {
        content,
        filename,
        record: {
          name: String(item.name).slice(0, 1000),
          kind: item.kind ? String(item.kind).slice(0, 80) : 'evidence-attachment',
          artifactPointer: `artifacts/${filename}`,
          artifactHash: sha256(content),
          bytes: content.length
        }
      };
    });
    const attachmentRecords = normalizedAttachments.map((item) => item.record);
    const record = buildEvidenceRecord({
      id,
      projectId,
      missionId,
      taskId,
      type,
      summary,
      sourceIdentity,
      runtimeIdentity,
      artifactPointer,
      artifactHash,
      attachments: attachmentRecords,
      metadata
    });

    const createdFiles = [];
    try {
      if (artifactContent !== null) {
        const full = path.join(this.store.artifactsDir, artifactFilename);
        createdFiles.push(full);
        await fs.writeFile(full, artifactContent, { mode: 0o600 });
      }
      for (const attachment of normalizedAttachments) {
        const full = path.join(this.store.artifactsDir, attachment.filename);
        createdFiles.push(full);
        await fs.writeFile(full, attachment.content, { mode: 0o600 });
      }
      await this.store.transaction('evidence_recorded', (state) => {
        attachEvidenceRecord(state, record);
      }, { evidenceId: id, type, projectId, missionId, taskId, attachmentCount: attachmentRecords.length });
      return record;
    } catch (error) {
      if (!isStateCommitAuditOutcomeUnknown(error)) await cleanupUncommittedFiles(createdFiles);
      throw error;
    }
  }

  async readQueryImages(records, { maxImages = 1 } = {}) {
    if (!Array.isArray(records)) throw new TypeError('evidence image content requires queried evidence records');
    const requested = Number(maxImages ?? 1);
    const imageLimit = Number.isInteger(requested) ? Math.max(1, Math.min(requested, MAX_QUERY_IMAGES)) : 1;
    const artifactsRoot = path.resolve(this.store.artifactsDir);
    const realArtifactsRoot = await fs.realpath(artifactsRoot);
    const images = [];
    let imageCount = 0;
    let totalBytes = 0;

    for (const record of records) {
      for (const attachment of Array.isArray(record?.attachments) ? record.attachments : []) {
        if (imageCount >= imageLimit) return images;
        if (attachment?.kind !== 'browser-screenshot') continue;
        const extension = path.extname(String(attachment.name || attachment.artifactPointer || '')).toLowerCase();
        if (extension !== REMOTE_SCREENSHOT_EXTENSION) continue;
        const bytes = Number(attachment.bytes);
        if (!Number.isInteger(bytes) || bytes <= 0 || bytes > MAX_QUERY_IMAGE_BYTES) {
          throw evidenceImageError('EVIDENCE_IMAGE_SIZE_INVALID', 'Evidence screenshot is outside the remote image size bound', {
            evidenceId: record.id,
            name: attachment.name,
            bytes: attachment.bytes,
            maxBytes: MAX_QUERY_IMAGE_BYTES
          });
        }
        if (totalBytes + bytes > MAX_QUERY_IMAGE_TOTAL_BYTES) {
          throw evidenceImageError('EVIDENCE_IMAGE_TOTAL_LIMIT', 'Evidence screenshots exceed the remote image total-byte bound', {
            maxBytes: MAX_QUERY_IMAGE_TOTAL_BYTES
          });
        }
        const pointer = String(attachment.artifactPointer || '');
        if (!pointer.startsWith('artifacts/')) {
          throw evidenceImageError('EVIDENCE_IMAGE_POINTER_INVALID', 'Evidence screenshot pointer is not runtime-owned', {
            evidenceId: record.id,
            name: attachment.name
          });
        }
        const full = path.resolve(artifactsRoot, pointer.slice('artifacts/'.length));
        let realFull;
        try {
          realFull = await fs.realpath(full);
        } catch (error) {
          throw evidenceImageError('EVIDENCE_IMAGE_READ_FAILED', 'Evidence screenshot artifact is unavailable', {
            evidenceId: record.id,
            name: attachment.name,
            cause: error?.code || 'READ_FAILED'
          });
        }
        const relative = path.relative(realArtifactsRoot, realFull);
        if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
          throw evidenceImageError('EVIDENCE_IMAGE_POINTER_INVALID', 'Evidence screenshot pointer escapes the runtime artifact root', {
            evidenceId: record.id,
            name: attachment.name
          });
        }
        const stat = await fs.stat(realFull);
        if (!stat.isFile() || stat.size !== bytes || stat.size > MAX_QUERY_IMAGE_BYTES) {
          throw evidenceImageError('EVIDENCE_IMAGE_INTEGRITY_MISMATCH', 'Evidence screenshot size no longer matches durable evidence metadata', {
            evidenceId: record.id,
            name: attachment.name,
            expectedBytes: bytes,
            actualBytes: stat.size
          });
        }
        const data = await fs.readFile(realFull);
        const actualHash = sha256(data);
        if (data.length !== bytes || actualHash !== attachment.artifactHash) {
          throw evidenceImageError('EVIDENCE_IMAGE_INTEGRITY_MISMATCH', 'Evidence screenshot bytes no longer match durable evidence metadata', {
            evidenceId: record.id,
            name: attachment.name,
            expectedBytes: bytes,
            actualBytes: data.length,
            expectedHash: attachment.artifactHash,
            actualHash
          });
        }
        if (data.length < PNG_SIGNATURE.length || !data.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) {
          throw evidenceImageError('EVIDENCE_IMAGE_FORMAT_INVALID', 'Evidence screenshot is not a valid PNG payload', {
            evidenceId: record.id,
            name: attachment.name
          });
        }
        totalBytes += data.length;
        imageCount += 1;
        images.push({
          evidenceId: record.id,
          attachment: String(attachment.name).slice(0, 240),
          sha256: actualHash,
          bytes: data.length,
          mimeType: REMOTE_SCREENSHOT_MIME_TYPE,
          data
        });
      }
    }
    return images;
  }

  async query({ projectId, missionId, taskId, type, ids, limit = 50 }) {
    const state = await this.store.read();
    let items = Object.values(state.evidence);
    if (ids !== undefined) {
      if (!Array.isArray(ids)) throw new TypeError('evidence ids must be an array when provided');
      items = ids.map((id) => state.evidence[id]).filter(Boolean);
    }
    if (projectId) items = items.filter((item) => item.projectId === projectId);
    if (missionId) items = items.filter((item) => item.missionId === missionId);
    if (taskId) items = items.filter((item) => item.taskId === taskId);
    if (type) items = items.filter((item) => item.type === type);
    return items.sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, Math.max(1, Math.min(limit, 200)));
  }
}
