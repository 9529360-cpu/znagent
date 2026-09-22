function integratedCheckpoint(before, after, waveIndex) {
  if (before.mission.phase !== 'execution' || after.mission.phase !== 'execution') return null;
  if (before.mission.nextWaveIndex !== waveIndex || after.mission.nextWaveIndex !== waveIndex) return null;
  const waveIds = after.mission.waves?.[waveIndex] || [];
  if (!waveIds.length) return null;
  const beforeById = new Map(before.tasks.map((task) => [task.id, task]));
  const afterById = new Map(after.tasks.map((task) => [task.id, task]));
  const waveTasks = waveIds.map((id) => afterById.get(id)).filter(Boolean);
  if (!waveTasks.length || waveTasks.every((task) => task.status === 'done')) return null;
  const newlyIntegrated = waveTasks
    .filter((task) => task.status === 'done' && beforeById.get(task.id)?.status !== 'done' && task.integrationSha)
    .sort((a, b) => a.id.localeCompare(b.id));
  const latest = newlyIntegrated.at(-1) || null;
  return latest ? { taskId: latest.id, commitSha: latest.integrationSha } : null;
}

export class FeedbackAwareWorkerOrchestrator {
  constructor({ delegate, missionService, runtimeFeedbackService, validationService = null }) {
    this.delegate = delegate;
    this.missionService = missionService;
    this.runtimeFeedbackService = runtimeFeedbackService;
    this.validationService = validationService;
  }

  async #liveCheckpointEnabled(mission) {
    const projectService = this.runtimeFeedbackService?.projectService;
    if (!projectService?.get || !mission?.projectId) return false;
    const project = await projectService.get(mission.projectId);
    return project.runtimeFeedbackPolicy?.liveSession === true;
  }

  async #runWithFeedback(missionId, operation) {
    const before = await this.missionService.status({ missionId });
    const result = await operation();
    const after = await this.missionService.status({ missionId });
    const rounds = [];
    let checkpoint = null;
    const start = before.mission.nextWaveIndex;
    const end = after.mission.nextWaveIndex;
    if (before.mission.phase === 'execution' && end > start) {
      for (let waveIndex = start; waveIndex < end; waveIndex += 1) {
        const feedback = await this.runtimeFeedbackService.runAfterWaveSafe({ missionId, waveIndex });
        const repair = await this.runtimeFeedbackService.scheduleRepairWaveSafe({ missionId, feedbackRound: feedback });
        rounds.push({ ...feedback, repair });
      }
    } else if (before.mission.phase === 'execution' && end === start) {
      const integrated = integratedCheckpoint(before, after, start);
      if (integrated && await this.#liveCheckpointEnabled(before.mission)) {
        checkpoint = await this.runtimeFeedbackService.runCheckpointSafe({
          missionId,
          waveIndex: start,
          targetCommitSha: integrated.commitSha,
          triggerTaskId: integrated.taskId
        });
      }
    }
    const latest = await this.missionService.status({ missionId });
    if (latest.mission.phase !== 'execution' && this.validationService) {
      await this.validationService.releaseRuntimeFeedbackSessions({ missionId, reason: `mission-${latest.mission.phase}` });
    }
    if (!rounds.length && !checkpoint) return result;
    return {
      ...result,
      ...(rounds.length ? { runtimeFeedback: rounds.length === 1 ? rounds[0] : rounds } : {}),
      ...(checkpoint ? { runtimeFeedbackCheckpoint: checkpoint } : {})
    };
  }

  execute(args) {
    return this.#runWithFeedback(args.missionId, () => this.delegate.execute(args));
  }

  commitExternalTaskResult(args) {
    return this.#runWithFeedback(args.missionId, () => this.delegate.commitExternalTaskResult(args));
  }

  resumeWorker(args) {
    return this.#runWithFeedback(args.missionId, () => this.delegate.resumeWorker(args));
  }

  cancelWorker(args) {
    return this.delegate.cancelWorker(args);
  }

  retryWorker(args) {
    return this.delegate.retryWorker(args);
  }
}
