import fs from 'node:fs/promises';
import path from 'node:path';
import { nowIso, randomId } from './util.mjs';

export class HandoffService {
  constructor({ store, missionService }) {
    this.store = store;
    this.missionService = missionService;
  }

  async export({ missionId }) {
    const { mission, tasks, candidates } = await this.missionService.status({ missionId });
    const readiness = await this.missionService.readiness({ missionId });
    const state = await this.store.read();
    const project = state.projects[mission.projectId];
    const evidence = Object.values(state.evidence).filter((item) => item.missionId === missionId).map((item) => ({ id: item.id, type: item.type, summary: item.summary, sourceIdentity: item.sourceIdentity, createdAt: item.createdAt }));
    const experiences = Object.values(state.experiences).filter((item) => item.projectId === mission.projectId && item.status === 'active').map((item) => ({ id: item.id, mechanism: item.mechanism, statement: item.statement, evidenceIds: item.evidenceIds, sourceIdentity: item.sourceIdentity }));
    const handoff = {
      schema: 'veteran-handoff-v1',
      exportedAt: nowIso(),
      project: { id: project.id, name: project.name, repoPath: project.repoPath, sourceIdentity: project.sourceIdentity },
      mission,
      tasks,
      candidates,
      evidence,
      activeExperiences: experiences,
      timeline: state.runtime.timeline.filter((item) => item.missionId === missionId),
      readiness,
      nextSafeAction: readiness.nextAction || (readiness.ready ? mission.phase : null)
    };
    const id = randomId('handoff');
    const filename = `${id}.json`;
    const full = path.join(this.store.artifactsDir, filename);
    await fs.writeFile(full, `${JSON.stringify(handoff, null, 2)}\n`, { mode: 0o600 });
    return { id, artifactPointer: `artifacts/${filename}`, handoff };
  }
}
